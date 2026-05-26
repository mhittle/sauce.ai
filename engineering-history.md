# sauce.ai/news — Engineering history

Chronological log of architecture decisions, bugs hit, and fixes applied
to sauce.ai/news. This is the **condensed working history** — read it
end-to-end before making changes; it is kept under a ~14K-token budget so
a session can ingest it in a single `Read`.

How this file is structured:

- **Load-bearing production state** (immediately below) is durable. It is
  **never archived**, because it captures server-side state that is not
  in the repo and will reintroduce already-fixed bugs if lost.
- The chronological log keeps the **most recent entries in full**.
- Older entries are compressed into **Condensed history** (one short
  paragraph each). Their full verbatim text — root causes, calibration
  notes, file lists — lives in `engineering-history-archive.md`, which is
  consulted **on demand** when troubleshooting or needing deep context,
  **not** during normal onboarding.
- **Original product spec** is kept at the bottom (also never archived).
- Append a new dated section at the top of the chronological log whenever
  something meaningful happens (see
  `new-engineering-session-instructions.md`). When this file exceeds its
  budget, run the archive procedure in `engineering-session-wrapup.md`.

---

## Load-bearing production state (read before touching prod)

Not in the repo — re-derived here so it survives history condensation.
Also cross-referenced in `bugs.md` (BUG-001/002), `INSTALL.txt` §8/§9,
and `new-engineering-session-instructions.md` Step 10. If these conflict,
this section + `INSTALL.txt` win.

**Agent-fleet config (GitHub side, not in repo)**

- Repo **variable** `AGENTS_ENABLED=true` gates all six agent workflows
  (set it to anything else to halt the fleet). Secrets: `ANTHROPIC_API_KEY`
  (needs credits), `AGENT_PUSH_TOKEN` (fine-grained PAT — **expires**, see
  `manual-actions.md`), `AGENT_OPS_SECRET`, `SMOKE_TEST_USER/PASS`, `FTPP`.
  Full reference and the hard constraints: `agent-fleet.md`.

**Host / paths**

- GoDaddy cPanel/CloudLinux. Account `lt1ih6uyy2z6`. App root
  `~/public_html/sauce.ai/news`. venv
  `~/virtualenv/public_html/sauce.ai/news/3.11`. DB `lt1ih6uyy2z6_news`
  (MySQL via PyMySQL). Live at https://sauce.ai/news.
- Secrets live ONLY in cPanel "Setup Python App" env vars (canonical
  source of truth — not in the repo, not in `.env`): DB creds,
  `ANTHROPIC_API_KEY`, optional `SMTP_*`, `FEED_JITTER`, `DISCOVER_*`.

**Load-bearing files / symlinks (recreate if lost)**

- Three symlinks in `~/public_html/sauce.ai/news/`: `activate`,
  `set_env_vars.py`, `python3.11_bin` → the real venv `bin/` files
  (BUG-001). If missing, the CloudLinux venv shim resolves `${CWD}` to
  the app root and Passenger fork-bombs. Recreate:
  ```
  cd ~/public_html/sauce.ai/news
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/activate activate
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/set_env_vars.py set_env_vars.py
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/python3.11_bin python3.11_bin
  ```
- `~/passenger_wsgi.py.working` — backup of the correct wsgi (BUG-002).
  cPanel may re-scaffold a self-recursive `passenger_wsgi.py` on App
  recreate / Python-version change; the repo version is correct, restore
  with `cp`.
- `~/htaccess.working` — backup of the env-vars `.htaccess` (carries the
  DB password + Anthropic key; sensitive even though uncommitted).
- `~/news-db-YYYYMMDD.sql` — DB snapshot taken after the first
  successful run.
- Harmless clutter: `~/public_html/sauce.ai/news/jobs/*.bak-*` (BUG-009
  in-place patch backups, superseded by the merged deploy; safe to
  delete at leisure).

**Hard rules**

- Do NOT set `APPLICATION_ROOT` in cPanel env vars — double-prefix 404s
  every URL (BUG-004).
- Never set `dangerous-clean-slate: true` in
  `.github/workflows/main.yml` — it wipes the symlinks/backups above.
  Incremental sync (`false`) is correct.
- CloudLinux nproc/EP limit is tight (~115). On `fork: Resource
  temporarily unavailable`: Stop the Python App in cPanel first, then
  pkill python, wait 60s.
- pip installs are run from cPanel Terminal inside the venv (the cPanel
  "Run Pip Install" button is greyed out). `trafilatura` was installed
  this way (PR #21).
- After any deploy that changes routes/blueprints/templates, restart the
  Python App in cPanel (Passenger caches imports until restart).

**Cron (in the cPanel crontab, not in the repo)**

`fetch_feeds` 15m · `classify_pending` 5m ·
`classify_pending --triggered-only` 1m (PR #121, demand-driven top-up;
no-op unless the feed touched `logs/classify_topup.signal`) ·
`popularity_poll` 30m ·
`trending_poll` 30m · `maintenance` nightly 03:30 UTC ·
`send_digest` 12:00 UTC · `discover_harvest` hourly :15 ·
`discover_promote` 04:00 UTC · `discover_llm` Mon 05:00 UTC. Each line
`source`s the venv `activate` and appends to `logs/cron.log`; all
wrapped in `job_lock` (fcntl) so an overlapping tick no-ops.
`trending_poll` now also rebuilds the `trending_topics` /
`trending_topic_articles` snapshot (the /trending page) each tick in
addition to the `article_features.trending` scalar — same single
30-min cron, no new entry.

**Applied prod schema migrations (not re-run automatically)** — see
`manual-actions.md` Completed for copy-paste SQL: `popularity_signals`
gained `permalink`/`subreddit` (PR #52, discussion links);
`article_features` gained `trending FLOAT` (PR #53, external trending
sort); new `user_saves` table (PR #64, article save / bookmark —
applied 2026-05-17, BUG-007 recurrence: trailed the merge by minutes
and 500'd signed-in `/` until run); new `trending_topics`/
`trending_topic_articles` tables (PR #71, /trending page); FULLTEXT
index `ft_articles_search` on `articles(title, summary)` (PR #70,
article search); new `user_term_prefs` table (PR #77, per-user
keyword mute/boost; `routes/feed.py` reads it on every signed-in feed
load — BUG-007 class if absent); new `algorithm_term_prefs` table
(PR #82, per-algorithm keyword mute/boost; applied 2026-05-20 —
`routes/feed.py` reads it for the active algorithm on every signed-in
feed load, same BUG-007 class); 12 new `article_features` columns
(PR #84, perceptual feature expansion — 6 LLM-judged + 6 rule-based;
applied 2026-05-20, BUG-007 class for `classify_pending` every 5-min
tick); `shared_algorithms.keywords_json` column added + `user_term_prefs`
table dropped (PR drafted 2026-05-20, keywords-on-algo only; applied
2026-05-21 — BUG-007 class for `gallery.adopt()` SELECTing the new
column); new `lab_concept_votes` table (PR drafted 2026-05-20,
root-domain landing page voting; applied 2026-05-21 — **NOT** BUG-007
class, only the new `/news/labvotes/*` endpoints touch it and the
landing page hides the vote UI on tally failure so the cards still
render). A DB rebuild from `seed/schema.sql` already includes
these.

---

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-26

- **BUG-025 — duplicate algorithm profiles in the feed switcher (PR
  drafted).** User reported the front-page "Algorithm:" dropdown listing
  the same names many times over. Root cause was not a query fan-out:
  `feed._switcher_profiles()` SELECTs `user_algorithms` with no JOIN and
  the template renders one `<option>` per row, so the dropdown faithfully
  mirrors real rows. Duplicates accumulate because `gallery.adopt()` and
  `algo.create_profile()` always `INSERT` a new row with no same-name
  guardrail (re-adopting "Lefty" or re-saving a named profile stacks
  another). Fix (owner chose "prevent + de-dupe display"): both write
  paths now reuse an existing same-named profile — update its weights
  (adopt also wipes+reinserts its `algorithm_term_prefs` keywords) and
  re-activate, instead of inserting; and a new pure helper
  `feed._dedupe_switcher_rows(rows)` collapses duplicate names in the
  dropdown (keeps the active-or-most-recent row per name; active id
  resolved from the full set). This also tidies the *existing* prod dupe
  rows in the UI without deleting them (non-destructive by request).
  *Code:* `app/routes/feed.py`, `app/routes/algo.py`,
  `app/routes/gallery.py`; tests `test_feed_switcher.py` (new),
  `test_gallery_adopt.py` (new), `test_algo_profiles.py` (extended).
  Full suite 563 passed. *Server state:* none — app-layer only, no
  migration/cron/env/dep, Passenger restart on deploy as usual.

### 2026-05-22

- **Unique sources toggle — one article per source (PR drafted,
  unattended dev-agent).** Per-profile boolean on `/algo`'s UI tab that
  tightens the global per-source cap to 1 for the viewer. User framing:
  "let me see a wider spread of sources, not three Inquirer stories in a
  row." This is the user-controllable lever over the BUG-021 cap
  (`FEED_MAX_PER_SOURCE`, default 3) already enforced by
  `app/feed_diversify.py`. No DB migration, no new env var, no new cron,
  no new dep — the flag is a new key `unique_sources` (boolean) inside
  the existing free-form `user_algorithms.weights_json`; the ranking
  layer already ignores unknown keys, so older profiles read the key as
  "off" without backfill (NOT BUG-007 class). New pure helper
  `feed_diversify.effective_source_cap(weights, default_cap)` — toggle on
  → 1 regardless of the global cap (including when configured to 0 /
  disabled); toggle off / absent → `default_cap`; never weakens an
  already-tighter floor. `feed.index()` now resolves the effective cap
  per request and clamps `fetch_budget(...)` to a new
  `feed_diversify.MAX_FETCH_ROWS = 5000` ceiling so deep "Load more"
  paging under cap=1 (multiplier ~31x) can't issue an unbounded `LIMIT`;
  a short page near the end of the 7-day window is acceptable, an
  unbounded fetch is not. Scope: `/` only — `/firehose`, `/search`,
  `/saved`, and the digest are untouched (same scoping as BUG-021). The
  cap is applied AFTER the SQL `ORDER BY`, so each source's surviving
  article is the highest-ranked one for that source under the user's
  algorithm; story-cluster dedup, jitter, source/keyword prefs,
  category/sort, the 7-day window, and pagination stability (page N+1
  agrees with page N) are unchanged. *Code touched:*
  `news/app/feed_diversify.py` (+`MAX_FETCH_ROWS` constant,
  +`effective_source_cap` helper), `news/app/routes/feed.py` (resolve
  effective cap via `effective_source_cap(weights, default_cap)` and
  clamp `fetch_budget(...)` at `MAX_FETCH_ROWS`),
  `news/app/routes/algo.py` (`_parse_form_weights` writes
  `weights["unique_sources"] = bool(form.get("unique_sources"))` on every
  save so toggle-off clears a previously-saved truthy value — unchecked
  HTML checkboxes don't submit),
  `news/app/templates/algo.html` (+`Unique sources` feature-row with the
  checkbox under Country filter, above Near a place — feed-shaping
  control, not a per-feature slider, so it sits next to recency /
  category / country rather than inside the weight grid). 10 new tests
  in `test_feed_diversify.py` and `test_algo_unique_sources.py` pin
  toggle-on/off/missing, override of a disabled global cap, "never
  weakens a tighter floor," no-duplicate-source-ids regression, and
  `MAX_FETCH_ROWS` ceiling sanity. Full suite: 530 passed. *Server
  state touched:* none — template + thin-route + pure-helper change;
  Passenger restart on deploy as usual.
- **Demand-driven feed classification (PR #121, unattended dev-agent).**
  Closes the "feed runs dry until the next 5-min cron tick" gap when an
  active reader outpaces `classify_pending`. **No synchronous LLM on the
  request path, no per-request fork/spawn** (nproc ceiling untouched):
  feed page size 30→40, and after each feed load the route does two cheap
  `COUNT(*)`s and, if the classified buffer ahead of the reader is < 400,
  **touches** `logs/classify_topup.signal` (mtime-debounced ~60s,
  failure-swallowed). `classify_pending.py` gains `--triggered-only`
  (new every-1-min cron) which no-ops unless the signal is present AND
  fresh, then acquires the existing `job_lock` and consumes the signal
  inside it — so the cron stays the only process that launches a
  classifier and the `*/5` tick remains the safety net. No migration /
  schema / pip / restart. New pure `app/classify_topup.py` + 23 tests
  (543 pass). *Code:* `app/classify_topup.py` (new), `routes/feed.py`,
  `app/config.py` (4 `CLASSIFY_TOPUP_*` knobs), `jobs/classify_pending.py`,
  `INSTALL.txt`, `tests/test_classify_topup.py`. *Server state:* one new
  1-min cron entry (`manual-actions.md` Open, full crontab line inline).
  No migration file → no `has-migration` label.
- **Unique sources toggle — one article per source (spec'd + dispatched,
  PM session).** New `ready-for-agent` roadmap item authored and merged
  to `main` (PR #123), which dispatched the unattended Opus dev-agent
  (~$8 paid run) to implement it. Feature: a per-profile checkbox on
  `/algo` (UI tab) that forces the home feed to **at most one article per
  source**. Design chosen to be migration-free and not BUG-007 class —
  the flag rides as a new `unique_sources` boolean key inside the
  existing free-form `user_algorithms.weights_json` (the ranking layer
  ignores unknown keys; `parse_weights_json` round-trips the dict), and
  the read path reuses the BUG-021 `app/feed_diversify.py` cap machinery
  with the *effective* per-source cap forced to 1 (overriding the global
  `FEED_MAX_PER_SOURCE` default of 3). Spec'd surfaces: `routes/algo.py`
  `_parse_form_weights`, `templates/algo.html` (feed-shaping checkbox, not
  a feature-row), `routes/feed.py` `index()` effective-cap resolution, and
  a pure `effective_source_cap` helper for unit tests; over-fetch ceiling
  flagged so cap=1 deep-paging can't issue an unbounded `LIMIT`. Scoped to
  `/` only (firehose/search/saved/digest unchanged). *Server state
  touched:* none planned (no migration/cron/env/dep). *Open:* the
  dev-agent's implementation PR is pending — review + merge it through the
  BUG-007 gate; no `needs-migration` follow-up expected.

- **Fold per-algorithm Keywords into the Your Algorithm feature list (PR
  drafted, unattended dev-agent).** UI polish on PR #82 + the
  keywords-on-algo migration: the standalone **Keywords** tab on `/algo`
  is gone; the add form + muted/boosted lists now render as a sibling
  `.features.features-keywords` panel below the algo-form (sibling, not
  nested, so per-keyword `<form>`s don't nest inside `#algo-form`). No DB
  / route / ranking change — `/algo/keywords/{add,<id>/delete}` writes,
  `_render_editor` context, and mute-wins/dedupe/100-cap semantics all
  preserved; pytest green (520). *Code touched:*
  `templates/algo.html`, `static/style.css` (+6 lines). *Server state:*
  none (template-only; cPanel restart recommended on deploy).

- **Agent fleet observability — weekly cost + activity rollup (PR
  drafted, unattended dev-agent).** Closes the loop opened by the six
  Phase-1..6 agent workflows shipped 2026-05-21 (PRs #103..#108): each
  workflow carries a per-run budget cap but nothing aggregates what the
  fleet actually *did*. Now: one append-only `agent_runs` row per agent
  run (workflow, job, run_id, conclusion, duration_seconds,
  est_cost_usd, pr_number, notes; mirrors the `llm_usage` table
  pattern). A new HMAC-authenticated `POST /agent-ops/report-run`
  endpoint (same `AGENT_OPS_SECRET` key as the Phase 4 executor —
  no new secret) accepts the row from a final "Report agent run"
  step appended to each of the six agent jobs (dev-agent.implement,
  qa-code.bug007-gate, post-deploy.agent-qa, migration-executor.finalize,
  bug-triage.triage, pm-agent.propose). The reporting step is gated
  `if: always()` so a failed agent still records a row; a shared
  `.github/scripts/report_agent_run.py` Python script signs and POSTs
  via stdlib only (no new deps) and is failure-tolerant — any error
  (missing secret, DNS, 5xx) logs and exits 0 so the reporting step
  can never break the actual agent workflow. The per-job budget cap
  is sent as `est_cost_usd` (with `notes:"budget-cap"` so future
  iterations can swap in measured cost from action output without a
  schema change). Read by new admin-only `GET /admin/agent-activity`
  in the existing `admin_ops` blueprint: 14-day per-workflow rollup
  (runs, successes, failures, total cost) + zero-filled per-day series
  + totals; degrades to `table_missing: true` (still 200) if the
  migration hasn't been applied yet, so the admin page never 500s.
  PM agent (Phase 6) can now cite this endpoint instead of inferring
  fleet activity from PRs. *Code touched:*
  `news/seed/migrations/2026-05-22-agent-runs.sql` (new),
  `news/seed/schema.sql` (+`agent_runs` CREATE TABLE after `llm_usage`),
  `news/app/routes/agent_ops.py` (+`/report-run` route + pure helpers
  `_int_in_range`, `_decimal_in_range`, regex validators),
  `news/app/routes/admin_ops.py` (+`/agent-activity` route),
  `news/app/security.py` (`agent_ops.report_run` added to
  `_EXEMPT_ENDPOINTS` — HMAC over body is a stronger guard than CSRF
  cookies a machine caller can't carry, same reasoning as the other
  three `agent_ops.*` endpoints),
  `.github/scripts/report_agent_run.py` (new), and a "Mark agent
  start" + "Report agent run" step appended to dev-agent.yml,
  qa-code.yml, post-deploy.yml, migration-executor.yml,
  bug-triage.yml, pm-agent.yml. 10 new tests in `test_admin_ops.py`
  and `test_agent_ops.py` (insert + clamping + invalid-workflow +
  invalid-conclusion + HMAC enforcement + zero-fill + missing-table
  degradation). *Server state touched:* one new migration —
  `manual-actions.md` Open entry with full inline SQL; the PR
  self-labels `needs-migration` so the Phase 4 executor applies it.
  No new env var, no new cron, no new pip dep, no restart needed
  (both routes attach to already-registered blueprints).

- **Agent fleet operationalized + hardened (interactive session).** Took
  the six merged-but-dormant workflows (PRs #103–#108) live and fixed
  every gap the first real runs surfaced. Enablement: set
  `AGENTS_ENABLED=true` + the secrets (`ANTHROPIC_API_KEY`,
  `AGENT_PUSH_TOKEN`, `AGENT_OPS_SECRET`, smoke creds) and topped up API
  credits. Fixes: (1) **headless tool permissions** — `claude-code-action`
  auto-denies tool calls without a permission mode, so workers use
  `--permission-mode bypassPermissions` and the BUG-007 gate (untrusted
  diffs) uses `dontAsk` + a tight `--allowedTools` allowlist (PR #111);
  (2) **event constraint** — the action only runs on
  `pull_request*`/`issues`/`issue_comment`/`repository_dispatch`, NOT
  push/schedule/workflow_dispatch, so dev-agent (PR #113) and
  pm-agent/post-deploy (PR #116) do their logic then fan out a
  `repository_dispatch` via `AGENT_PUSH_TOKEN` (the default
  `GITHUB_TOKEN` can't trigger downstream runs); picker push now
  rebases+retries (PR #116); (3) **migrate-after-deploy** —
  `/agent-ops/run-migration` reads the file from prod disk, so migrations
  apply only post-deploy: the dev agent now labels migration PRs
  `has-migration` and a human applies `needs-migration` after deploy
  (PR #115). The #114 `agent_runs` migration was applied to prod this way.
  Docs: `agent-fleet.md` (fleet reference, PR #117) and
  `pm-session-instructions.md` (this PR). #120 (demand-driven feed
  classification) dispatched; implementation PR in flight. *Load-bearing
  fleet config lives in `agent-fleet.md`.*

### 2026-05-21

- **Agent infrastructure cluster — six phases, all merged (PRs #103-#108).**
  Shipped the unattended agent fleet: P1 dispatcher (ready-for-agent ->
  Opus dev PR), P2 pre-merge BUG-007 QA gate, P3 post-deploy verification
  (+ read-only `admin_ops` blueprint), P4 HMAC migration/restart executor
  (`agent_ops` blueprint), P5 bug auto-triage, P6 weekly PM agent. Gated by
  `AGENTS_ENABLED`; uses `AGENT_PUSH_TOKEN` / `ANTHROPIC_API_KEY` /
  `AGENT_OPS_SECRET` / `SMOKE_TEST_*`. Full per-phase detail (files,
  endpoints, budgets, the human setup checklist) is in the archive;
  operational reference is `agent-fleet.md`; load-bearing config is in
  "Load-bearing production state" above. Operationalized + hardened
  2026-05-22 (see that entry).

### 2026-05-20

All entries condensed; full verbatim in `engineering-history-archive.md`
(grep by PR#). Migrations are folded into "Applied prod schema
migrations" above.

- **Lab landing expansion +10 concepts + anon voting (PR drafted)** —
  root `index.html` grew to 1 live + 17 coming-soon cards with HN-style
  ▲/▼ voting; new pure `app/lab_concepts.py` + `app/routes/lab.py`
  (`/labvotes/tally`+`/vote`, CSRF-exempt), `lab_concept_votes` table
  (NOT BUG-007 class). Migration applied 2026-05-21.
- **Root sauce.ai/ landing page (PR drafted)** — first in-repo
  `index.html` at the domain root (FTP-published by main.yml);
  product-lab positioning + 8 product cards. No server state.
- **Keywords-on-algo only — drop /terms (PR drafted)** — keywords now
  live only on each algorithm profile; `user_term_prefs` dropped, rows
  folded into the active profile; gallery publish/adopt carry keywords
  via new `shared_algorithms.keywords_json` (sanitized). Migration
  applied 2026-05-21 (BUG-007 class).
- **`.gitattributes` `merge=union`** for the 5 high-conflict tracking
  docs; trade-off (dup rows / out-of-order headers) documented in the
  instructions §7.4. Docs-only.
- **Gallery follow-ons** — per-profile "Publish to gallery" button
  (PR #94); Copy-link + Email share buttons (PR #95). Template/route
  only, no server state.
- **Source catalog re-import on prod (PR #91 follow-up)** — admin
  "Re-import seed CSV" run on prod (768→1919 sources). manual-actions
  Completed.
- **BUG-022 topnav overflow** — `.topnav` `flex-wrap` + smaller font/gap.
  CSS-only.
- **Shareable algorithm gallery v1 (PR #88)** — publish / browse /
  adopt-as-new-active-profile + 3 usage stats; `shared_algorithms` +
  `algorithm_adoptions` (migration applied 2026-05-20; NOT BUG-007
  class). `/gallery`.
- **Source catalog +1151 (PR #91)** — `seed/source_lean.csv` 768→1919;
  idempotent admin import. No code change.
- **BUG-021 single-source feed domination (PR #89)** — new pure
  `app/feed_diversify.py` caps N per source on `/` (`FEED_MAX_PER_SOURCE`
  default 3). No server change.
- **Perceptual feature expansion +12 features (PR #84)** — 6 LLM + 6
  rule-based features into `FEATURES`/`article_features`; migration
  applied 2026-05-20 (BUG-007 class for `classify_pending`).
- **Per-algorithm keyword mute & boost (PR #82)** —
  `algorithm_term_prefs` table + `/algo` Keywords tab; migration applied
  2026-05-20 (BUG-007 class).
- **Compact / density toggle (PR #81)** — client-only `data-density`
  localStorage toggle on `/`. No server change.

### 2026-05-18

- **Why This Article ranking explainer (PR #79).** "Why?" toggle lazily
  loads a per-feature score breakdown; new pure `app/explain.py` imports
  the direction/scale helpers from `ranking.py` so it can't desync (18
  parity tests). No server change. Full detail: archive.

### 2026-05-17

All entries condensed; full verbatim in `engineering-history-archive.md`
(grep by PR#). Migrations folded into "Applied prod schema migrations".

- **Keyword/topic mute & boost (PR #77)** — per-user `user_term_prefs`
  (mute = filter, boost = multiplier); pure `app/term_prefs.py`;
  migration applied 2026-05-17 (BUG-007 class). Later superseded by
  keywords-on-algo (2026-05-20).
- **BUG-020 firehose accumulation (PR #72)** — firehose now accumulates
  via a keyset cursor on `(classified_at, id)`; pure
  `app/firehose_cursor.py`. No server change.
- **Across-the-spectrum in-feed (PR #69)** — "+N angles" pill expands
  inline to sibling-outlet coverage; pure `app/spectrum.py`. No server
  change.
- **Full-text article search (PR #70)** — `/search` + nav box on a
  MySQL FULLTEXT index over `articles(title, summary)`; FULLTEXT
  migration applied 2026-05-17.
- **Trending topics view /trending (PR #71)** — ranks topics by
  distinct-outlet count, reusing the `trending_poll` index;
  `trending_topics` + `trending_topic_articles` applied 2026-05-17.
- **Multiple saved algorithms / profiles (PR #65)** — app-layer only
  (no migration); profile switcher on `/`.
- **Dark mode (PR #63)** — client-only `data-theme` toggle, no-FOUC head
  init. No server change.
- **Article save / bookmark (PR #64)** — `user_saves` + `/saved`;
  maintenance exempts saved from retention prune; migration applied
  2026-05-17 (BUG-007 recurrence — trailed the merge).
- **Onboarding interview / cold-start (PR #62)** — real cold-start
  interview; pure `app/onboarding.py`; no migration.
- **Classifier/feature review BUG-016..019 (PR #56)** — popularity
  under-count, byline rep penalty, simhash==0 megacluster, LLM-fallback
  contamination. Cron-script + helper only; no server change.
- **CSRF + auth rate limiting (PR #58)** — hand-rolled signed
  double-submit CSRF app-wide; sliding-window login/signup limit. No
  migration.
- **Natural-language algorithm builder (PR #59)** — plain-English →
  `FEATURES` weights via one Haiku call, pre-fills `/algo`; pure
  `app/algo_nl.py`; no migration. Shipped the user-empowerment cluster.
- **BUG-015 external trending sort (PR #53)** — `app/trending.py` +
  `trending_poll` cron fill `article_features.trending`; "Trending"
  sort. Migration + 30-min cron applied 2026-05-17.
- **Discussion links Reddit/HN (PR #52)** — persist permalink+subreddit
  on `popularity_signals`; pure `app/discussion.py`. Migration applied
  2026-05-17.
- **Engineering-history archive process (PR #51)** — introduced this
  archive + the ~14K-token budget + the durable load-bearing section.
  Docs-only.
- **BUG-013/014 Latin-script language filter (PR #50)** — stage-3
  `py3langid` detector in `app/language.py`; swapped langdetect→py3langid
  (wheel). `pip install` run on prod 2026-05-17.

### 2026-05-14

- **Feed sort selector — Relevance / Newest / Popularity (PR #48).**
  `/?sort=` query param swaps the ORDER BY via `_normalize_sort` +
  `_order_by_for_sort` in `feed.py`; filters unchanged; category tabs +
  Load-more preserve `sort=`. *Server:* none.

### 2026-05-13

All entries below are condensed; archive has full verbatim detail.
Load-bearing server state is already folded into "Applied prod schema
migrations" above where relevant.

- **BUG-012 (PR #46)** — feed was deterministic; added opt-in `jitter`
  kwarg to `build_score_sql` (live feed reads `FEED_JITTER`, default
  0.10; digest/firehose/preview stay deterministic). No server change.
- **English-only fetch-time filter (PR #42)** — pure
  `app/language.py is_english`: stage 1 trusts non-English `<language>`
  tag, stage 2 rejects >25% non-Latin letters. Latin-script EU gap later
  closed by BUG-013/014. No server change.
- **Story dossier v1 — `/story/<id>` (PR #43)** — multi-source view of a
  deduped cluster; `story_dossiers` caches a Haiku framing summary
  keyed by member-signature, gated 3+ members / 2+ lean buckets;
  "+N angles" pill on feed cards. *Server:* `story_dossiers` migration.
- **Mobile / responsive polish (PR #40)** — single `@media (max-width:640px)`
  block + `.table-scroll`; desktop untouched. CSS only.
- **Automated source discovery — Reddit/HN + LLM (PR #38)** —
  `candidate_sources` + 3 crons (`discover_harvest` hourly,
  `discover_promote` 04:00, `discover_llm` Mon 05:00) +
  `/admin/discovery` queue. *Server:* migration + 3 cron entries.
- **BUG-011 — multiplicative recency gate (PR #34)** — additive ranking
  let stale-but-quality dominate; switched recency to
  `score = quality * EXP(-r*h/24)` (recency=0 = legacy).
- **BUG-010 — feature bars (PR #35)** — template wrote
  `style="width:NN%"` but CSS reads `--w` custom property; switched to
  `style="--w:NN%"`.
- **BUG-008/009 — classify_pending stall (PR #32)** — idle MySQL sockets
  dropped during LLM/HTTP gaps → `conn.ping(reconnect=True)` at every idle
  point; parallelized paywall+body HTTP; throughput 10→180/tick. Lesson:
  ping-reconnect any cron HTTP-between-writes.
- **BUG-007 recovery (PRs #30/#31)** — code referenced `sources.owner_id`
  + `user_source_prefs` before migrations ran → 500s on every reader
  route. Lesson: treat Open `manual-actions.md` as a merge blocker.
- **Article deduplication (PR #24)** — `articles.simhash`+`story_id`;
  SimHash Hamming≤8 over 48h, canonical = highest reputation; feed dedupes
  by cluster, firehose doesn't. *Server:* dedup migration.
- **Manual-actions tracker (PR #22)** — docs-only.
- **User-added RSS feeds (PR #29)** — `/sources`; `sources.owner_id`
  scopes personal feeds. *Server:* `sources.owner_id` migration.
- **In-app reader view (PR #21)** — `article_bodies` + `app/extractor.py`
  (lazy trafilatura) in `classify_pending`; `/read/<id>`. *Server:*
  migration + `pip install trafilatura`.
- **Thumbs up/down + signal foundation (PR #19)** — `user_signals` +
  `user_source_prefs`; `/signal` blueprint. *Server:* signals migration.
- **Daily email digest (PR #23)** — opt-in `users.digest_enabled` + unsub
  token; noon-UTC `send_digest` cron; stdlib `smtplib`. *Server:* digest
  migration + noon-UTC cron.
- **Cron hardening + PyMySQL timeouts (PR #15)** — `job_lock(name)`
  fcntl mutex; `requests` timeouts; anthropic `timeout=30`; PyMySQL
  timeouts (web `(5,15,10)`, cron `(5,30,15)`); `FEED_FETCH_BATCH`
  80→20.

### 2026-05-12

*(Full verbatim for all 2026-05-12 entries is in
`engineering-history-archive.md`; load-bearing prod state is in the
durable section above.)*

- **Paywall feature (PR #14).** Per-article HTTP probe writes
  `article_features.paywall` 0..1; opt-in catalog entry. *Server:*
  paywall migration.
- **Editorial serif wordmark (PR #13).** `.brand` restyle. *Server:* none.
- **Feature batch #7–#11.** BUG-006 fix (article-link click navigation),
  category tabs, 3-axis feature config (Direction+Weight+Threshold),
  obscurity features (+migration), source catalog 135→768
  (auto-deactivate at `error_count=10`). *Server:* obscurity migration;
  +633 seed-CSV import.
- **Doc framework.** Added `roadmap.md`, `bugs.md`,
  `engineering-session-wrapup.md`. *Server:* none.
- **v1 prototype deploy to GoDaddy (PRs #3, #4).** First working deploy;
  fixed 5 deploy bugs BUG-001..005 (`APPLICATION_ROOT` double-prefix,
  INSTALL path mismatch, venv-shim fork-bomb, self-recursive
  `passenger_wsgi.py`, anthropic/httpx incompat → `0.101.0`). All
  not-in-repo state folded into **Load-bearing production state** above.
  Anthropic key + DB password were exposed in chat and rotated before close.

---

## Original product spec (for reference)

The user's initial framing of the project. Architecture decisions in v1 trace
back to this. Anything contradicting this spec was an intentional v1 scoping
decision (see "v1 limitations" above).

> I want to build and deploy a full stack news aggregator that allows people
> to aggregate the news that they like using different toggles. Essentially,
> this allows them to create their own newsfeed algorithm. We're using Google
> News as a starting point, but wanting something much more powerful and much
> more dense. The system should query thousands of RSS feeds and other news
> feeds daily, and then analyze each article based on the features that can be
> included in a users algorithm.
>
> There will be a main view, similar to google news that loads a users feed
> based on their algorithm. There will then be a Your Algo page that allows
> users to build their algorithm in several different ways:
> 1. via UI elements — toggles for binary elements, scale selectors for rated
>    elements and other natural ui features as appropriate
> 2. via python code — users should have a library of elements and features
>    to choose from, which can be incorporated into their own ranking
>    algorithm.
>
> The third view will be a firehose view, where a user can see all of the
> articles in the db as they stream in, along with some visual indicators of
> their ranking.
>
> The starting ranking will be based on 1. political lean 2. reading level
> 3. objectivity 4. information density 5. journalist reputation 6. news
> source lean 7. news source 8. category 9. geography 10. popularity
>
> You'll need to create a full stack web app that runs on a backend that can
> be supported by the Godaddy Webhosting Plus instance that we have, which
> runs CPanel and has VTP, PHP, Perl, Node.js, Ruby, and Python, and MySQL
> and phpMyAdmin. The backend should be as lightweight as possible, with a
> simple administration/management page that's built for me, who is technical.
> The backend should show the health of the RSS and data feeds, user
> management and IAM, traffic stats, content stats, as well as a management
> page for the different features used in classification and the algorithms.
>
> The first build will be very lightweight and not emphasize security or the
> backend admin as much. It will need to be a very solid prototype, with the
> customer facing UI being paramount. All of the security and backend can be
> refined later.
