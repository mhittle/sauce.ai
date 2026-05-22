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

`fetch_feeds` 15m · `classify_pending` 5m · `popularity_poll` 30m ·
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

### 2026-05-22

- **Fold per-algorithm Keywords into the Your Algorithm feature list (PR
  drafted, unattended dev-agent).** UI polish on top of the per-algo
  keyword work (PR #82) and the keywords-on-algo migration (2026-05-21):
  the standalone **Keywords** tab on `/algo` is gone; the add-keyword
  form, count + cap, and the muted/boosted term lists now render as a
  "Keywords" `feature-row` appended to the UI tab's existing feature
  list (right after Near a place). The block is a sibling
  `.features.features-keywords` panel directly below the algo-form
  rather than inside it, because the per-keyword `<form>` elements
  would otherwise nest inside `#algo-form` — invalid HTML. The CSS
  collapses the row to a 2-column grid (label + body) and the existing
  `.feature-row` mobile media query handles single-column stacking on
  narrow viewports. No DB change, no route change, no ranking-behavior
  change: `/algo/keywords/add` and `/algo/keywords/<id>/delete` still
  carry the writes, `_render_editor` still hands `algo_muted`,
  `algo_boosted`, `max_keywords`, `boost_default`, `kw_error`,
  `active_algo_id` to the template, mute-wins/dedupe/100-cap semantics
  are preserved, and the "Save an algorithm first" guard still renders
  when there is no active profile. The Keywords tab count
  (`Keywords (N)`) folds into a `.kw-inline-count` span next to the
  new feature-name label. No test asserted on the Keywords tab markup
  so no test changes were required; full pytest suite remains green
  (520 passed). *Code touched:* `news/app/templates/algo.html` (drop
  the `Keywords` tab `<button>` from `<nav class="tabs">`, drop the
  `<section x-show="tab==='keywords'">` block at the end of the page,
  add a `features-keywords` sibling block at the bottom of the UI
  section), `news/app/static/style.css` (+6 lines: `.features-keywords`
  margin, `.feature-keywords` 2-column grid override, `.kw-body`
  min-width:0, `.kw-lede` muted lede, `.kw-inline-count` count
  styling). *Server state touched:* none — no migration, no restart
  needed (template-only change picked up by Passenger on next worker
  cycle, but cPanel restart is still recommended for any deploy that
  changes templates).

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

### 2026-05-21

- **Agent infrastructure cluster — six phases, all merged this day.**
  The unattended agent fleet that replaces "5 Claude Code terminals
  per session." Every workflow is gated by repo variable
  `AGENTS_ENABLED`; agents push/PR via fine-grained PAT
  `AGENT_PUSH_TOKEN`; LLM calls use `ANTHROPIC_API_KEY`. Dev/PM = Opus
  4.7, QA/review/triage = Sonnet 4.6, executor-finalize = Haiku 4.5.
  Full detail per phase in the PRs; only load-bearing + setup state is
  kept here.
  - **P1 Dispatcher (PR #103).** `ready-for-agent` roadmap item →
    unattended Opus dev session → draft PR. Files:
    `.github/agents/dev-warmup.md` (unattended warmup; ASSIGNMENT block
    with `{{ASSIGNMENT_TITLE}}`; never moves manual-actions Open→Completed;
    draft-PR only; $8/45min budget; BLOCKED + PARTIAL protocols;
    self-labels `needs-migration` when it produces a migration),
    `.github/scripts/pick_ready_items.py` (stdlib picker: flips
    `ready-for-agent`→`in-progress` in the at-a-glance row + detail
    Status line, `[skip ci]` commit, emits `items=[...]`; idempotent),
    `.github/workflows/dev-agent.yml` (push-to-`roadmap.md` /
    workflow_dispatch; concurrency `dev-agent-picker`; implement matrix
    max-parallel 3).
  - **P2 Pre-merge QA + BUG-007 gate (PR #104).**
    `.github/workflows/qa-code.yml` on pull_request: `tests` job
    (always: pip install, `create_app()` boot, pytest) +
    `bug007-gate` (Sonnet $1, gated by AGENTS_ENABLED). Gate flags
    (a) new SQL refs in `news/app/**` or `jobs/*.py` absent from both
    `seed/schema.sql` and an Open manual-actions entry, (b) changes to
    passenger_wsgi/app `__init__`/config/jobs/requirements without a
    same-PR INSTALL.txt update, (c) HARD FAIL on
    `dangerous-clean-slate: true`. Verdict via `/tmp/bug007-verdict.txt`
    → 0/1 exit; `blocked-pre-merge` label on block.
    `.github/agents/qa-reviewer.md`. **Branch protection (manual):**
    require `tests`; require `bug007-gate` once AGENTS_ENABLED=true.
    Also fixed two pre-existing breakages the new `tests` job surfaced:
    `sgmllib3k` PEP-517 build failure (workaround: upgrade
    pip/setuptools/wheel + `--no-build-isolation feedparser`, per
    INSTALL.txt §2c) and a stale `test_csrf.py` assertion (`b"CSRF"` →
    `b"CSRF validation failed"`, since base.html now embeds
    `X-CSRF-Token` in JS).
  - **P3 Post-deploy verification (PR #105).** *App code (the one
    pre-Phase-4 exception):* new read-only admin blueprint
    `news/app/routes/admin_ops.py` — `GET /admin/cron-health` (last 200
    lines of `logs/cron.log`, `deque` tail, `CRON_LOG_PATH` override)
    and `GET /admin/usage-summary` (14-day signups/DAU/signals JSON,
    read-only SELECTs on existing tables — **no migration**). 6 tests.
    *Workflow:* `.github/workflows/post-deploy.yml` (push-to-main +120s
    sleep + cron `*/30`): `smoke` curl of /, /firehose, /algo,
    /trending, /search?q=test, /gallery (fail on 5xx) + `agent-qa`
    (Sonnet $2 Playwright MCP: sign in, thumb-persist, Keywords tab,
    firehose, cron-health scan; auto-files deduped `agent:qa-filed` bug
    PRs). `.github/agents/post-deploy-qa.md`. *Server:* Open
    manual-actions entry — Python App restart so `admin_ops` registers
    (NOT BUG-007 class). Needs secrets `SMOKE_TEST_USER` /
    `SMOKE_TEST_PASS` (admin account recommended for the cron-health
    scan).
  - **P4 Migration / restart executor (PR #106).** *App code:* new
    blueprint `news/app/routes/agent_ops.py` at `/agent-ops/*`, all
    HMAC-SHA256 authenticated over the request body keyed by
    `AGENT_OPS_SECRET` (±300s freshness; unset → 503 fail-closed):
    `run-migration` (filename whitelist basename-only `*.sql` resolved
    under `news/seed/migrations/`; split on `;`; one transaction;
    rollback on failure), `restart-app` (touch
    `<app_root>/../tmp/restart.txt`, `AGENT_OPS_RESTART_FILE` override),
    `verify-schema` (read-only parameterized information_schema SELECT,
    identifier-validated). Endpoints added to
    `security._EXEMPT_ENDPOINTS`; `AGENT_OPS_SECRET` /
    `AGENT_OPS_RESTART_FILE` in `config.py`. 19 tests. **DDL is not
    transactional in MySQL** — wrapper gives true rollback only for DML;
    keep migrations idempotent. *Workflow:*
    `.github/workflows/migration-executor.yml` on PR labeled
    `needs-migration`: `apply` (sign + POST each diffed migration +
    restart, fail loud) + `finalize` (Haiku $0.50: move manual-actions
    entry Open→Completed, comment, swap label →`migration-applied`).
    *Server:* Open manual-actions entry — set `AGENT_OPS_SECRET`
    (`openssl rand -hex 32`) in BOTH cPanel Setup-Python-App env AND a
    GitHub Actions repo secret, identical, quarterly rotation. No schema
    change.
  - **P5 Bug auto-triage (PR #107).**
    `.github/workflows/bug-triage.yml` on PR labeled `agent:qa-filed`
    (Sonnet $1): reads the new BUG-NNN, posts ONE verdict —
    `AUTO_FIX_ELIGIBLE` (fix <3 files, clear repro, not a sharp-edge
    area) or `NEEDS_HUMAN`; biased to NEEDS_HUMAN when unsure; read-only
    + one comment, never promotes. `.github/agents/bug-triage.md`. No
    server change.
  - **P6 PM agent (PR #108).** `.github/workflows/pm-agent.yml` on cron
    `0 14 * * 1` + workflow_dispatch (Opus $4): reads 14-day
    history/bugs/roadmap + the P3 admin endpoints (curl login with
    SMOKE_TEST_* , degrades gracefully), proposes ≤3 `status: proposed`
    roadmap items (data-cited Rationale) in ONE draft PR
    `PM proposals: <date>` touching detail sections only (never the
    at-a-glance table); empty weeks open nothing.
    `.github/agents/pm-agent.md`. Added `proposed` to roadmap status
    conventions. No server change.
  - **Setup the human must do before the loop is live:** create secrets
    `AGENT_PUSH_TOKEN` (contents+PR write PAT), `ANTHROPIC_API_KEY`,
    `AGENT_OPS_SECRET` (also in cPanel env), `SMOKE_TEST_USER` /
    `SMOKE_TEST_PASS`; set variable `AGENTS_ENABLED=true`; add branch
    protection (require `tests` + `bug007-gate`); restart the Python App
    twice (admin_ops blueprint + the AGENT_OPS_SECRET env). Tracked in
    `manual-actions.md` Open. Also moved two prior migrations
    (lab-votes, keywords-on-algo) to Completed (user-confirmed applied
    on prod 2026-05-21).

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
  `/?sort=` query param; `_normalize_sort` + `_order_by_for_sort`
  pure helpers in `feed.py` swap the ORDER BY (newest →
  `published_at`, popularity → `f.popularity`); threshold / source-
  pref / visibility filters unchanged; category tabs + Load-more
  preserve `sort=`. *Server:* none (restart on deploy).

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
- **BUG-008/009 — classify_pending stall (PR #32)** — GoDaddy MySQL
  drops idle sockets during LLM/HTTP gaps → `conn.ping(reconnect=True)`
  at every idle point in classify/popularity/fetch; parallelized
  paywall+body HTTP (10 workers); `CLASSIFY_BUDGET_SECONDS` 90→240;
  throughput 10→180/tick. Lesson: ping-reconnect any cron HTTP-between-writes.
- **BUG-007 recovery (PRs #30/#31)** — merged code referenced
  `sources.owner_id` + `user_source_prefs` before migrations ran →
  500s on every reader route. Lesson: treat Open `manual-actions.md`
  as a merge blocker.
- **Article deduplication (PR #24)** — `articles.simhash` +
  `articles.story_id` + `(story_id,published_at)` index; SimHash
  Hamming≤8 over 48h, canonical = highest reputation; feed dedupes by
  cluster, firehose doesn't. v2 = embeddings. *Server:* dedup migration.
- **Manual-actions tracker (PR #22)** — added `manual-actions.md`
  lifecycle. Docs-only.
- **User-added RSS feeds (PR #29)** — `/sources`; `sources.owner_id`
  scopes personal feeds; visibility filter in feed/firehose. *Server:*
  `sources.owner_id` migration.
- **In-app reader view (PR #21)** — `article_bodies` + `app/extractor.py`
  (lazy trafilatura, 1 MB cap, MIN_WORDS=60) in `classify_pending`;
  `/read/<id>`; nightly `BODY_RETENTION_DAYS` prune. *Server:* migration
  + `pip install trafilatura`.
- **Thumbs up/down + signal foundation (PR #19)** — `user_signals`
  (forward-compat for Signal Learning) + `user_source_prefs`;
  `/signal` blueprint. *Server:* signals migration.
- **Daily email digest (PR #23)** — opt-in `users.digest_enabled` +
  unsub token; noon-UTC `send_digest` cron; stdlib `smtplib`
  (localhost MTA default; `SMTP_*` env vars for a relay). *Server:*
  digest migration + noon-UTC cron.
- **Cron hardening + PyMySQL timeouts (PR #15)** — `job_lock(name)`
  fcntl mutex; `requests` timeouts; anthropic `timeout=30`; PyMySQL
  timeouts (web `(5,15,10)`, cron `(5,30,15)`); `FEED_FETCH_BATCH`
  80→20.

### 2026-05-12

- **Paywall feature (PR #14).** Active per-article HTTP probe in
  `classify_pending` writes `article_features.paywall` 0..1 (JSON-LD /
  `content_tier` / phrase heuristics; blocked → 0.5 "suspected");
  opt-in catalog entry; `/admin/feeds` paywall column. *Server:*
  paywall migration.
- **Editorial serif wordmark (PR #13).** `.brand` restyled in
  `base.html` + `style.css` (system serif; italic "news"). *Server:*
  none.
- **Feature batch #7–#11.** #7 fix **BUG-006** (article links: HTMX
  `hx-post` on the anchors → `onclick` fetch+keepalive so browser
  navigation works); #8 category tabs on `/`; #9 3-axis feature config
  (Direction + Weight + Threshold; uniform
  `weight*(1-|v-dir|/scale)`); #10 obscurity features (story + source,
  log-scaled) + migration; #11 source catalog 135→768 +
  auto-deactivate at `error_count=10` + `/admin/feeds` Refresh button.
  *Server:* obscurity migration; +633 seed-CSV import. Detail:
  `bugs.md` BUG-006.
- **Doc framework.** Added `roadmap.md`, `bugs.md` (BUG-001..005
  pre-populated), `engineering-session-wrapup.md`, and wired all into
  `new-engineering-session-instructions.md`. *Server:* none.
- **v1 prototype deploy to GoDaddy (PRs #3, #4).** First working
  deploy. Fixed 5 deploy bugs: `APPLICATION_ROOT` double-prefix 404
  (BUG-004), INSTALL path mismatch (BUG-005), CloudLinux venv-shim
  fork-bomb (BUG-001), cPanel self-recursive `passenger_wsgi.py`
  (BUG-002), `anthropic 0.39` / `httpx 0.28` incompat → bumped to
  `0.101.0` (BUG-003). All not-in-repo server state from this deploy is
  consolidated in **Load-bearing production state** above; root causes
  in `bugs.md` BUG-001..005 and `INSTALL.txt` §8. The Anthropic key +
  DB password were exposed in chat and rotated before close.

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
