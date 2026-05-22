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

## 2026-05-31

- **Breaking-news email alerts — spec finalized + dispatched (PM session, roadmap-only).**
  Pressure-tested the existing `in-progress` spec against the live code (Explore
  pass): `send_digest.py` already splits `smtp_send()` from message-building
  with the exact `MIMEMultipart("alternative")` + `List-Unsubscribe` block and
  `_ensure_unsub_token()` (mailer extraction = low risk); `account.py`
  `settings()` + digest toggle + CSRF-exempt `/account/unsubscribe/<token>`
  exist to mirror 1:1; cron bootstrap, Haiku client (`classify_batch_llm` →
  `LLMUnavailable`, `llm_usage` logging), schema columns, and the `BREAKING_*`
  config pattern all confirmed present. **One spec correction:**
  `term_prefs.build_term_clauses` is SQL-clause-only — there is **no** pure
  matcher to reuse, so the spec now says *extract* a pure `term_matches(text,
  term)` into `term_prefs.py` and have both the SQL builder and
  `breaking.is_suppressed` call it (one matcher, two callers). **Owner product
  decision:** ship **live on deploy — NO shadow/dry-run mode** (PM recommended
  a default-on `BREAKING_DRY_RUN` to calibrate the firing rate on the now-1,919-feed
  catalog before any real send; owner declined). Compensating asks folded into
  the spec: `BREAKING_MIN_OUTLETS`/`WINDOW_HOURS`/`MAX_PER_DAY` must stay
  env-tunable, the cron must log a structured per-tick audit line
  (candidates/verdicts/recipients), and the three guards (fail-closed LLM gate,
  per-story dedup, per-user daily cap) plus `BREAKING_ENABLED` kill-switch carry
  the safety. Status flipped `in-progress → ready-for-agent` (row + detail);
  merging the dispatch PR to `main` fires the paid (~$8) dev run. No code this
  session.
- **PM session — backlog prioritization + two Google-News-inspired specs (this
  session; roadmap-only).** Owner asked to prioritize the backlog, then pivoted
  to "new features that take advantage of the best parts of Google News."
  Framed Google's real strengths (habit-forming *surfaces*, not personalization
  — which is our turf) against sauce.ai's under-used assets, and shaped three:
  **News Near You** (local section over the `geo_*` columns we already compute
  but only expose as a buried `/algo` slider), **The Brief** (Top Stories rail
  with inline spectrum spread — the missing front-page hook), and a dossier
  **story timeline**. Wrote two **build-ready** roadmap items (detail + matching
  at-a-glance rows, byte-identical titles):
  - **News Near You — `ready-for-agent` (DISPATCHED, ~$8 dev run on merge to
    `main`).** Pri 7 / LOE 4. A `/local` page that injects a page-chosen place
    into a *copy* of the active weights and reuses the existing feed query path
    verbatim (so it's "my algorithm, filtered to my place"), reusing
    `app/geo.py` (`geocode_query` / `haversine_sql`) + the geo filter already
    in `ranking.build_filters_sql`. Place via `?place=` + a `local_place`
    cookie (no table). **NOT BUG-007 class — no migration/cron/env/dep**;
    US-only in v1 (US Census gazetteer). The one open engineering call left to
    the dev agent: extract `feed.index()`'s query into a shared builder vs.
    reuse the smaller building blocks (fallback documented).
  - **The Brief — `backlog` (tracked, NOT dispatched).** Pri 7 / LOE 4. A Top
    Stories rail above `/`'s feed cards: top N multi-outlet clusters by
    distinct-outlet count (internal, not the Google-gated trending snapshot),
    each with an `L·C·R` spectrum chip (`spectrum.lean_bucket`) linking to the
    dossier. Page-1/non-HTMX/no-category only, degrades to empty on any failure.
    NOT BUG-007 class — additive read path, no migration.
  - No code change this session. Dispatch note: the row is `ready-for-agent` on
    branch `claude/wizardly-wozniak-TOR5s` — the picker fires on **push to
    `main`**, so the paid dev run launches when this roadmap PR is **merged**,
    not on the branch push.

- **BUG-029 — NL `/algo` chat box doesn't create per-algorithm keywords (interactive session, PR #142 merged, docs-only).** User: describing a feed in the `/algo` chat box doesn't create keywords for that algorithm. Code on `main` (PR #140) is correct end-to-end (`algo_nl.py` returns a sanitized `keywords` list; `describe()` passes `nl_keywords`; `algo.html` renders chips with hidden `nl_kw_*` inputs inside `#algo-form`; `save()`/`create_profile()` call `_apply_nl_keywords()` -> `algorithm_term_prefs`; `test_algo_nl.py` 21/21). User confirmed **no chips appear and none after reload**, which rules out the Save-refresh gap and points to a **stale Passenger worker**: PR #140's new route needs a restart to take effect (the template auto-reloads, so the old route serves no keywords -> `kws=[]` -> no chips). Filed the missing **PR #140 restart** as a `manual-actions.md` Open entry (BUG-029) with browser/DB verification; fallback if chips still missing post-restart = Haiku omitting the `keywords` array (`app/algo_nl.py` prompt/parse), not the deploy. **No code change** this session; BUG-029 stays `open` pending the prod restart + re-test. Renumbered BUG-028->029 after rebase (parallel session merged BUG-028 = the "Why?" explainer 500). *Process gap:* PR #140 shipped 2026-05-27 without a restart manual-action, same class as BUG-007/025.
- **BUG-030 — orthogonal algorithms surfaced the same articles; split
  SELECTION from RANKING on `/` (interactive session, PR #144 MERGED
  2026-05-31).** User:
  switching to a different, supposedly orthogonal algorithm showed "a lot
  of the same articles." Review (no crash/arithmetic bug) found a design
  conflation: feature weights only fed a single `score` used for
  `ORDER BY` — they never changed *membership* (the `/` candidate set is
  the whole classified/canonical/7-day/visible pool minus the hard filters
  in `build_filters_sql`), and the multiplicative recency gate dominated
  that score so the freshest rows floated up under almost any weight
  vector. Owner chose the user's model — **weights pick what's in the
  list, sort picks the order**. Fix: new `ranking.build_affinity_sql`
  (recency-free, L1-normalized weighted feature match in [0,1]; returns
  `("1", {})` when unweighted); `feed.index()` now SELECTs both `affinity`
  and the recency-gated `score`, `ORDER BY affinity DESC LIMIT
  FEED_SELECTION_POOL` to pick the candidate SET, caps per source, then
  re-orders via new pure `feed_diversify.rank_for_display(rows, sort)`
  (relevance→score, newest→published_at, trending→trending). Recency moved
  to the ranking stage only — does **not** regress BUG-011 (order still
  recency-gated). Scope `/` only (firehose/search/saved/`/algo`
  preview/digest keep the single-score `build_score_sql`). *Code:*
  `app/ranking.py`, `app/feed_diversify.py`, `app/routes/feed.py`,
  `app/config.py` (+`FEED_SELECTION_POOL`, default 600), `INSTALL.txt`,
  `tests/test_ranking.py` (+6 affinity), `tests/test_feed_sort.py`
  (rank_for_display replaces the removed `_order_by_for_sort`). No
  migration/cron/dep; Passenger restart on deploy. Detail: `bugs.md`
  BUG-030 (renumbered from BUG-028 → BUG-029 → BUG-030 — parallel sessions
  merged a different BUG-028 ("Why?" explainer 500) and BUG-029 (NL builder
  chat-box keywords) first). Rebased 4x behind fast-moving parallel
  sessions; the code stayed conflict-free, only the union-merge tracking
  docs thrashed (two ID collisions + a triplicated history bullet, each
  cleaned in the rebase). **Post-deploy:** needs a Passenger restart for
  the new `feed.index()` route (shared with the PR #140/#145 restarts) +
  a browser check that two orthogonal profiles surface different sets —
  `manual-actions.md` Open (2026-05-31).
- **Manual-actions reconciliation.** User confirmed all three Open items
  done; moved to Completed (2026-05-31): every-1-min
  `classify_pending --triggered-only` cron (PR #121, also **BUG-023 fix
  A**), PR #119 Python App restart, and `AGENT_PUSH_TOKEN` rotation.
- *(History ~33 KB, just under the ~34 KB budget — archive the oldest
  dated entries at the next wrap-up to regain headroom.)*

---

## 2026-05-27

- **Article summary — 3-bullet TL;DR (roadmap Pri 7, interactive session, PR
  #145 merged).** New per-article TL;DR generated by
  Haiku and cached in a new `article_summaries` table; surfaces via a "TL;DR"
  toggle on feed cards (lazy HTMX, like "Why?") and a box atop the reader view.
  **Owner chose the separate-pass-from-body design** over folding into the
  load-bearing judgments call: a new isolated LLM pass
  (`app/classifier/summary.py` `summarize_batch_llm`) runs in
  `jobs/classify_pending.py` *after* body extraction, over the gated subset
  only (`source_reputation > SUMMARY_MIN_REPUTATION=0.4` AND
  `paywall < SUMMARY_MAX_PAYWALL=0.5` AND a real extracted body) — summarizes
  the actual article, not the RSS blurb, and any failure is swallowed so it can
  never degrade ranking or stall classification. **BUG-025 lesson applied:**
  classify probes `_table_exists("article_summaries")` once per run and skips
  the pass if the migration is absent, so a missing migration produces no
  summaries instead of freezing the feed; the read path (`app/article_summary.py`
  `load_bullets`) catches a missing table and degrades to an empty panel, so the
  reader/feed routes never 500 pre-migration. Summary LLM usage is logged to
  `llm_usage`; the cron line gains a `summaries=N` field. *Code:*
  `app/classifier/summary.py` (new), `app/classifier/__init__.py`,
  `app/article_summary.py` (new), `app/config.py` (5 `SUMMARY_*` knobs),
  `jobs/classify_pending.py`, `app/routes/feed.py` (+`/article/<id>/summary`),
  `app/routes/reader.py`, `app/templates/partials/{feed_cards,summary_panel}.html`,
  `app/templates/reader.html`, `app/static/style.css`,
  `seed/schema.sql` + `seed/migrations/2026-05-31-article-summaries.sql`,
  `tests/test_article_summary.py` (+11 pure tests; full suite 582 pass),
  `INSTALL.txt`. *Server state:* one new migration (`manual-actions.md` Open,
  full inline SQL) + a Python App restart on deploy (new route/blueprint
  surface). No new cron, no new env var required (knobs default), no new pip
  dep.
  dep. Migration applied post-deploy via `needs-migration`.

- **"Tune from this article" — article-anchored weight nudges (interactive
  session, PR pending).** Shipped the Signal-Learning *wedge* (roadmap Pri 7,
  LOE 4): each feed card carries signed-in **More / Less like this** buttons
  that lazily load a preview of which feature *weights* would change and by
  how much, with **Accept** / **Undo** — nothing persists until Accept. New
  pure `app/tune.py`: nudge = `±LEARNING_RATE·(2·alignment − 1)` per
  *already-weighted* feature, where `alignment = 1 − |value − direction|/scale`
  is the scorer's own per-feature factor (imported from `ranking`, same parity
  discipline as `explain.py`, so it can't desync from `build_score_sql`).
  "More" boosts aligned features / trims misaligned; "Less" flips sign;
  clamped to `[0, 2]`; sub-`MIN_DELTA` and zero-weight features dropped. Apply
  **recomputes server-side** (never trusts client deltas) and mutates the
  active profile's existing `weights_json` — **no new adjustment-vector
  table**, so the full Signal Learning regression can later absorb it (roadmap
  note); Undo merges the pre-nudge weights back (re-sanitized, known keys
  only). Three thin feed-bp routes (`GET/POST /article/<id>/tune`,
  `POST …/tune/undo`); directions/thresholds/filters/keywords untouched.
  *Code:* `app/tune.py`, `routes/feed.py`,
  `templates/partials/{tune_panel,tune_applied,tune_reverted}.html` +
  `feed_cards.html`, `static/style.css`, `tests/test_tune.py` (12 pure).
  **No migration/cron/env/dep — Passenger restart on deploy.**
- **BUG-028 — "Why?" explainer 500'd on every click (fixed, same PR).** Found
  while reusing `_active_weights()` for Tune: it was changed to return a
  `(weights, active_algo_id)` tuple and `feed.index()` updated to unpack it,
  but the older `explain()` route still passed the tuple to
  `explain_article()` (`.get()` on a tuple → `AttributeError`) — broken since
  ~2026-05-20, uncaught because `explain.py`'s tests call it with a dict.
  One-line fix `weights, _ = _active_weights()`. See `bugs.md` BUG-028.
- **Manual-actions queue drained.** User confirmed all three Open prod actions
  done → moved to Completed: `AGENT_PUSH_TOKEN` rotated, PR #119 restart, and
  the 1-min `classify_pending --triggered-only` cron (installed 2026-05-27 as
  BUG-023 fix A). `manual-actions.md` Open is now empty.
- **Roadmap: added "Steel-man — strongest opposing-view coverage of a story"
  (backlog, Pri 7 / LOE 3; PR #146).** One-click strongest opposing coverage
  on multi-source cards + the `/story` dossier, re-aiming existing
  spectrum/dossier machinery (`pick_spectrum_sample`, `story.peek`,
  `_fetch_cluster`, shared ±0.2 lean buckets); "strongest" = highest
  `source_reputation`×`objectivity` opposing-bucket article (steel-man, not
  strawman). v1 deterministic + LLM-free, no migration, NOT BUG-007 class.
  Spec block + at-a-glance row only — left `backlog`, not `ready-for-agent`,
  so no dev-agent dispatch.
- **History archived to budget (this wrap-up).** Live file had grown to ~38 KB
  (over the ~34 KB single-Read ceiling); moved the verbose 2026-05-22 entries
  verbatim into `engineering-history-archive.md` and replaced them with tight
  summaries → ~29.5 KB.

---

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-27

- **NL algorithm builder now also proposes keywords (interactive session, PR
  pending).** `/algo`→`/describe`'s single Haiku call now also returns a
  `{term, mode, weight}` keyword list, sanitized via the `term_prefs` helpers
  and kept **out** of `weights_json`. Review-then-Save UX: proposed keywords
  render as removable pending chips and persist only on Save (new
  `_apply_nl_keywords()` re-sanitizes server-side). *Code:* `algo_nl.py`,
  `routes/algo.py`, `algo.html`, `style.css`, `test_algo_nl.py`. No
  migration/cron/env/dep.

### 2026-05-26

- **BUG-025 — feed frozen at May 20 (PR #135 merged).** `classify_pending`
  crashed every tick on `Unknown column 'geo_lat'`: the 2026-05-20 geo
  migration was wired into `schema.sql`/the INSERT but never applied on prod
  and never tracked — a BUG-007-class miss on the cron *write* path, silent
  (no user 500) for 6 days while `pending` grew to ~57k. Fix: applied the
  migration on prod (no code change); backlog self-drains. **Lesson: any
  migration adding a cron-written column needs a `manual-actions.md` Open
  entry at merge time.**
- **BUG-027 — future-dated article pinned to top; downvote didn't remove it
  (PR #137 draft, in-progress).** Future `published_at` made the recency
  multiplier > 1 (unbounded boost); clamped age with `GREATEST(..., 0)` in
  `ranking.py`. Also the signed-in `/` feed now excludes `thumb_down` ids.
- **BUG-026 — duplicate algorithm profiles in the feed switcher (PR
  drafted).** `gallery.adopt()`/`algo.create_profile()` inserted same-named
  rows; both now reuse the existing same-named profile, and a pure
  `feed._dedupe_switcher_rows()` collapses duplicate names in the dropdown.

### 2026-05-22

- **Unique sources toggle — one article per source (PR #124/#125 dev-agent;
  spec'd + dispatched via PR #123, PM session).** Per-profile `/algo` checkbox
  forcing at most one article per source on `/`; rides as a `unique_sources`
  bool inside `user_algorithms.weights_json` (ranking ignores unknown keys —
  NOT BUG-007 class). New pure `feed_diversify.effective_source_cap` +
  `MAX_FETCH_ROWS=5000` over-fetch ceiling for cap=1 deep paging. `/` only;
  no server state. (Verbatim design in archive.)
- **Demand-driven feed classification (PR #121, dev-agent).** Feed touches
  `logs/classify_topup.signal` when the classified buffer ahead of the reader
  drops < 400; a new `classify_pending --triggered-only` every-1-min cron
  no-ops unless the signal is fresh, then runs under the existing `job_lock`
  (the `*/5` tick stays the safety net). No sync LLM, no per-request spawn;
  page size 30→40. New `app/classify_topup.py`. *Server:* one 1-min cron —
  installed on prod (manual-actions Completed 2026-05-31; BUG-023 fix A).
- **Fold per-algorithm Keywords into the Your Algorithm feature list
  (PR #119, dev-agent).** Dropped the standalone `/algo` Keywords tab; the
  add-form + muted/boosted lists render as a sibling `.features-keywords`
  panel. Template/CSS only — no DB/route/ranking change.
- **Agent fleet observability — weekly cost + activity rollup (PR #114,
  dev-agent).** Append-only `agent_runs` row per agent run via HMAC
  `POST /agent-ops/report-run`; read by admin `GET /admin/agent-activity`
  (14-day rollup, degrades to `table_missing` if unapplied — never 500s).
  *Server:* `agent_runs` migration (applied 2026-05-22, manual-actions
  Completed).
- **Agent fleet operationalized + hardened (interactive session).** Took the
  six dormant workflows (PRs #103–#108) live: `AGENTS_ENABLED=true` + secrets
  + API credits, and fixed headless tool perms (PR #111), the
  `repository_dispatch` event constraint + push rebase/retry (PRs #113/#116),
  and migrate-after-deploy via `has-migration`/`needs-migration` labels
  (PR #115). Docs: `agent-fleet.md` (PR #117), `pm-session-instructions.md`.
  *Load-bearing fleet config lives in `agent-fleet.md`.*
Full verbatim in `engineering-history-archive.md` (grep by date / PR#).
- **Breaking-news email alerts (PR drafted, unattended dev-agent).**
  First push channel that reaches an opted-in reader between digests.
  Detection rides distinct-outlet counting (the same signal that powers
  `/trending`): the new `breaking_alerts` cron (every 15 min) selects
  stories whose `story_id` is covered by >= `BREAKING_MIN_OUTLETS`
  (default 12) distinct global outlets (`s.owner_id IS NULL`) in the
  last `BREAKING_WINDOW_HOURS` (default 6), dedupes against
  `breaking_news_alerts` (UNIQUE on `story_id`), and confirms each
  survivor via one Haiku call with strict JSON
  `{is_major, headline, blurb}`. Fail-closed on `LLMUnavailable` — no
  row recorded so a later tick retries while still in window;
  rejections ARE recorded so the cron does not re-judge them every 15
  min. For each confirmed event, every opted-in user is sent an email
  unless the event headline matches an active-profile mute term
  (`algorithm_term_prefs`, same case-insensitive substring semantics
  as `app.term_prefs._MATCH_EXPR` so the two matchers can't drift) or
  the user is at their `BREAKING_MAX_PER_DAY` cap (default 3, tracked
  via `alerts_day` / `alerts_today` with UTC rollover). The opt-in
  toggle lives next to (but separate from) the daily-digest toggle on
  `/account/settings`, with its own `unsub_token` so unsubscribing
  from one channel doesn't touch the other. New
  `/account/alerts/unsubscribe/<token>` route (CSRF-exempt, mirrors
  the digest pattern). **NOT BUG-007 class** — both new tables are
  separate from `users`, and `settings()` / the cron / the
  unsubscribe route all tolerate them being missing (the cron is a
  fast no-op, the settings page renders the toggle as off, and the
  unsubscribe link surfaces "already unsubscribed"). Label the PR
  `has-migration`, not `needs-migration` — the executor applies the
  migration post-deploy per `agent-fleet.md`. The cron orchestrator
  is in `jobs/breaking_alerts.py`; all decision logic
  (`select_candidates`, `is_suppressed`, `daily_cap_ok`,
  `parse_llm_verdict`) lives in pure `app/breaking.py` so the
  21 new tests in `test_breaking.py` don't need Haiku/DB/SMTP. A
  small `app/mailer.py` (build_message + smtp_send) was extracted
  from `jobs/send_digest.py` so both senders share one
  `MIMEMultipart('alternative')` + RFC 8058 `List-Unsubscribe` block
  (`send_digest.py` is behavior-preserving after the refactor; the
  one `test_digest.py` monkeypatch was moved from
  `send_digest.smtplib.SMTP` to `app.mailer.smtplib.SMTP`). Full
  suite: 574 passed (was 553). *Code touched:*
  `news/seed/migrations/2026-05-22-breaking-alerts.sql` (new),
  `news/seed/schema.sql` (+`user_alert_prefs`,
  +`breaking_news_alerts`, both near `lab_concept_votes`),
  `news/app/breaking.py` (new, pure helpers),
  `news/app/mailer.py` (new, shared SMTP helper),
  `news/jobs/breaking_alerts.py` (new cron),
  `news/jobs/send_digest.py` (refactor to use mailer),
  `news/app/templates/breaking_email.html` +
  `news/app/templates/breaking_email.txt` (new),
  `news/app/routes/account.py` (+breaking-news toggle in `settings()`,
  +`alerts_unsubscribe` route),
  `news/app/templates/account_settings.html` (+toggle section),
  `news/app/config.py` (+4 `BREAKING_*` env knobs),
  `news/app/security.py` (`account.alerts_unsubscribe` added to
  `_EXEMPT_ENDPOINTS`),
  `news/INSTALL.txt` (env knobs + new cron line),
  `news/tests/test_breaking.py` (new, 21 tests),
  `news/tests/test_digest.py` (monkeypatch target updated for the
  mailer extraction). *Server state touched:* one new migration
  (`manual-actions.md` Open entry with full inline SQL, two new
  tables) + one new cron line (every 15 min). No new env var is
  strictly required (defaults are sane); reuses the existing `SMTP_*`
  config; no new pip dep; no new secret. Passenger restart on deploy
  so the updated `account` blueprint registers
  `/account/alerts/unsubscribe/<token>`.
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

- **Unique sources toggle — one article per source (PR drafted; PM-spec'd via
  PR #123, ~$8 dev-agent run).** Per-profile `/algo` checkbox forcing <=1
  article/source on `/`; rides as a `unique_sources` bool inside
  `user_algorithms.weights_json` (NOT BUG-007 class), reusing the BUG-021
  `feed_diversify` cap with the effective cap forced to 1 plus a
  `MAX_FETCH_ROWS=5000` over-fetch ceiling. `/` only. No migration/cron/env/dep.
- **Demand-driven feed classification (PR #121).** Feed touches
  `logs/classify_topup.signal` when the classified buffer < 400; a new
  every-1-min `classify_pending --triggered-only` cron consumes it under
  `job_lock` (the `*/5` tick stays the safety net). Page size 30->40. New pure
  `app/classify_topup.py`. One 1-min cron (now Completed).
- **Fold per-algorithm Keywords into the feature list (PR drafted).** Dropped
  the standalone `/algo` Keywords tab; the add form + muted/boosted lists now
  render as a sibling `.features-keywords` panel. Template/CSS only.
- **Agent fleet observability (PR #114).** Append-only `agent_runs` table + HMAC
  `POST /agent-ops/report-run` (reuses `AGENT_OPS_SECRET`) written by all six
  agent jobs; read by admin `GET /admin/agent-activity` (14-day rollup, degrades
  if the table is absent). Migration applied (Completed).
- **Agent fleet operationalized + hardened (interactive).** Took the six dormant
  workflows (PRs #103-#108) live: `AGENTS_ENABLED=true` + secrets + API credits;
  fixed headless tool perms (PR #111), `repository_dispatch` fan-out via
  `AGENT_PUSH_TOKEN` (PRs #113/#116), and migrate-after-deploy via
  `has-migration`/`needs-migration` (PR #115). Fleet reference: `agent-fleet.md`.

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

### 2026-05-12 — 2026-05-14 (condensed digest)

*All entries below are one-line digests; **full verbatim is in
`engineering-history-archive.md`** (grep by PR# / BUG-ID) and every
load-bearing migration/cron is in the durable sections above.*

- **2026-05-14:** Feed sort selector (PR #48) — `/?sort=` swaps ORDER BY
  (`_normalize_sort`/`_order_by_for_sort`); tabs + Load-more preserve `sort=`.
  No server.
- **2026-05-13:** BUG-012 feed jitter `FEED_JITTER`=0.10, digest/firehose
  deterministic (PR #46) · English-only fetch filter `app/language.py` (PR #42)
  · Story dossier `/story/<id>`, `story_dossiers` migration (PR #43) · Mobile
  polish, CSS (PR #40) · Automated source discovery Reddit/HN+LLM,
  `candidate_sources` + 3 `discover_*` crons (PR #38) · BUG-011 multiplicative
  recency gate `quality*EXP(-r*h/24)` (PR #34) · BUG-010 feature-bar `--w` fix
  (PR #35) · BUG-008/009 classify_pending idle-socket stall →
  `ping(reconnect=True)` + parallel HTTP, 10→180/tick (PR #32) · BUG-007
  recovery: missing migrations 500'd reader routes — treat Open
  manual-actions as a merge blocker (PRs #30/#31) · Article dedup
  simhash+story_id, dedup migration (PR #24) · Manual-actions tracker (PR #22)
  · User-added RSS `/sources`, `sources.owner_id` migration (PR #29) · In-app
  reader `/read/<id>`, `article_bodies` migration + `pip install trafilatura`
  (PR #21) · Thumbs up/down, `user_signals`+`user_source_prefs` migration
  (PR #19) · Daily digest, digest migration + noon cron (PR #23) · Cron
  hardening + `job_lock` + PyMySQL timeouts (PR #15).
- **2026-05-12:** Paywall feature, paywall migration (PR #14) · Editorial
  serif wordmark (PR #13) · Feature batch #7–#11: BUG-006 click-nav, category
  tabs, 3-axis feature config, obscurity features (+migration), source catalog
  135→768 · Doc framework `roadmap.md`/`bugs.md`/wrap-up · v1 prototype deploy
  to GoDaddy (PRs #3/#4): fixed BUG-001..005, not-in-repo state folded into the
  Load-bearing section, exposed Anthropic key + DB password rotated before close.

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
