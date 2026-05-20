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
feed load, same BUG-007 class). A DB rebuild from `seed/schema.sql`
already includes these.

---

## 2026-05-20 — BUG-021 single-source feed domination (per-source cap, PR #89)

User reported the `/` feed was filled with Philadelphia Inquirer
articles under different algorithms ("weird recency bias"). Logged as
BUG-021 (PR #87, docs-only, merged); fix shipped in PR #89.

### Root cause

`app/routes/feed.py index()` had no per-source diversification. The
query ordered by `score DESC` (or `published_at` / `f.trending`
depending on `?sort=`) and took the top 30. Dedup was per-`story_id`
(cluster), not per-source — so a source with a recent fetch burst, or
with high `source_reputation` plus the BUG-011 multiplicative recency
gate hitting many rows at once, legitimately rose into all 30 slots
until ~24h decay broke it up. BUG-012's score jitter shuffles within a
tier but doesn't cap any one source.

### What shipped

- **`app/feed_diversify.py`** (new, Flask-free / DB-free, mirrors
  `app/spectrum.py` / `app/firehose_cursor.py`): `cap_per_source(rows,
  cap=N, key="source_id")` keeps at most N rows per source preserving
  input order; `fetch_budget(page, page_size, cap)` returns the SQL
  row budget needed to guarantee a full page after capping;
  `page_slice` slices the requested page out of the capped list. 14
  pure tests in `tests/test_feed_diversify.py` (cap behavior,
  over-fetch sizing, pagination stability across pages, 50-row
  same-source burst regression).
- **`app/routes/feed.py`**: `index()` now reads
  `current_app.config["FEED_MAX_PER_SOURCE"]`, calls `fetch_budget()` to
  set the SQL `LIMIT` (always `OFFSET 0`), runs `cap_per_source()` over
  the result, then `page_slice()` to return the requested page.
  Pagination is stable: page N+1 sees the same capped sequence as page
  N (it's a deterministic prefix function of the SQL row order).
- **`app/config.py`**: new `FEED_MAX_PER_SOURCE` (default 3,
  env-tunable; 0 disables — the cap can be killed without a deploy).
- **`news/INSTALL.txt`** §10: documented v1 limits of the cap.
- **`bugs.md`**: BUG-021 entry moved to Resolved with root-cause +
  fix narrative.

### Scope choices

- **Python cap, not a SQL window function.** `ROW_NUMBER() OVER
  (PARTITION BY a.source_id ...)` would be cleaner but needs MySQL 8 /
  MariaDB 10.2+; staying in Python keeps the fix shared-host-agnostic
  and unit-testable without a live DB.
- **`/` only.** `/firehose` is intentionally un-deduped; `/search` is
  intentionally relevance-ordered with story-cluster dedup; `/saved`
  is the user's own bookmarks; the email digest already caps at
  `DIGEST_MAX_ARTICLES` (default 8) and per-source dilution is less
  visible there. Each can be added later by passing the same cap.
- **Cap is applied AFTER the existing ORDER BY**, so the survivors
  preserve the ranking that brought them in. The "first 3 by score"
  per source are kept regardless of which `?sort=` is active.

### Server-side state touched

None. No DB / cron / env / pip / symlink change. Standard Python App
restart on deploy.

### Verification

`tests/test_feed_diversify.py` 14/14 green via the sandbox driver (no
pytest in sandbox — documented limit). Changed Python `py_compile`
clean. Route-level / browser verification deferred to CI / real env
(sandbox lacks Flask + PyMySQL).

### Known limits

- Worst case where all sources in the rolling 7-day window come from a
  single source, the cap leaves the page short rather than refilling
  from outside the over-fetch window. Not reachable at the real
  catalog size (~768 active sources).
- The over-fetch multiplier sizes for `cap=3` / `page_size=30`. If a
  future tuning drops the cap to 1 with the same page size we'd need
  to revisit the multiplier (covered by `fetch_budget`'s logic but
  unit-tested only at the current defaults).

### Rebase

Branch was rebased onto `origin/main` mid-session after PRs #82, #83,
#84 (perceptual feature expansion), #85, #86, and #87 landed. Only
conflict was `engineering-history.md` (both this entry and PR #84 are
dated 2026-05-20 — hand-resolved by keeping both, BUG-021 newest);
INSTALL.txt §10 and `app/routes/feed.py` auto-merged cleanly with no
overlap.

### PRs

- **PR #87** — BUG-021 log entry (merged 2026-05-20, docs-only).
- **PR #89** — per-source cap implementation.

---

## 2026-05-20 — Perceptual feature expansion: 12 new ranking features (PR #84)

Roadmap "Perceptual feature expansion" (Pri 7 / LOE 5, algo/backend) —
user-requested mid-session pivot from the original onboarding pick.
Doubles the size of the `FEATURES` catalog (12 → 24) by adding 6
LLM-judged perceptual signals and 6 rule-based structural ones, both
batched into the existing classify pipeline (no new cron, no new
LLM request).

### What shipped

- **`app/classifier/rules.py`** — 6 new pure scorers:
  `headline_length_score` (normalized title word count, cap 24),
  `caps_ratio_score` (uppercase ratio over letters in title),
  `punctuation_intensity_score` (!? per word, scaled),
  `numeric_density_score` (digit-runs per word, scaled),
  `question_headline_score` (0/1), `quote_present_score` (0/1, straight
  and smart quotes). Wired into `compute_rules_features` return dict.
- **`app/classifier/schema.py` + `app/classifier/llm.py`** — extended
  the Haiku system prompt to ask for 6 perceptual fields per article
  (`tone_calmness`, `sensationalism`, `analysis_depth`,
  `emotional_charge`, `hedging`, `solution_orientation`); parser
  clamps each to [0,1], defaults missing fields to 0.5. New
  `LLM_PERCEPTION_KEYS` constant + `LLM_PERCEPTION_DEFAULT = 0.5`.
- **`jobs/classify_pending.py`** — `_run()` INSERT extended to write
  all 12 new columns (LLM-unavailable rows get 0.5 across the 6
  perceptual ones, mirroring how the existing fallback treats
  `objectivity`); `_reclassify_nollm` UPDATE extended to also heal
  the 6 LLM features when the bounded reclassify pass runs.
- **`app/ranking.py`** — 12 new entries in `FEATURES` with modest
  default weights (0.1–0.5) and sensible default_directions
  (preferring calm/non-sensational/analytical/neutral; no preference
  on hedging/headline-length/solution/data/quote). Because existing
  `user_algorithms.weights_json` doesn't reference the new keys,
  `build_score_sql` skips them for legacy users — opt-in via the
  /algo editor, where the existing `{% for feat in features %}` loop
  auto-renders the 12 new rows.
- **`seed/schema.sql` + `seed/feature_catalog.sql`** — 12 new columns
  on `article_features` and 12 new catalog rows.
- **Migration** `seed/migrations/2026-05-20-perception-features.sql`
  (ADD COLUMN x12 + INSERT x12).
- **Tests** — `tests/test_rules.py` (15 new pure scorer cases,
  in-sandbox green), `tests/test_ranking.py` (5 new — catalog
  shape, SQL contribution, threshold, legacy compat),
  `tests/test_llm_unavailable.py` (1 new — perception constants
  shape), `tests/test_classify_pending.py` (existing reclassify
  test updated to expect the 8-field UPDATE shape).
- **INSTALL.txt §10** — new entry documenting the 12 features,
  fallback semantics, cost delta (~3x prior per-article LLM cost,
  still sub-$0.001/article), no-backfill behavior, and migration
  dependency.

### Server-side state touched

- **One manual DB migration** logged Open in `manual-actions.md` with
  full inline SQL: `2026-05-20-perception-features.sql`
  (12 ADD COLUMN on `article_features` + 12 INSERT into
  `feature_catalog`). **Load-bearing (BUG-007 class):**
  `classify_pending` INSERTs into the new columns on every 5-min
  tick after deploy and errors hard if they're missing. Apply
  before merge / before the next deploy; restart the Python App on
  deploy. Existing user feeds keep rendering normally throughout
  (their algos don't reference the new keys); only the classify
  cron breaks if the migration is missed.
- No new cron / env-var / symlink / pip dep.

### Verification

- 84 sandbox-runnable tests in the changed area green
  (`test_rules.py`, `test_ranking.py`, `test_llm_unavailable.py`,
  `test_classify_pending.py`); 174 total in the full sandbox-runnable
  subset green. The 6 collection errors are the documented
  environmental sandbox limitation (no flask/feedparser — same
  pattern as PR #50/#53/#59/#69/#70/#77). Changed Python files
  `py_compile` clean.
- Full route + browser exercise of the editor (12 new sliders
  render, save+reload preserves them, scores reflect tuned values)
  and a real classify_pending tick (writes non-default values for
  the new LLM + rule fields) deferred to CI / real env.

### Rebase / conflicts

Rebased once mid-session onto `origin/main` after PRs #79 (Why This
Article), #80, #81 (compact toggle), #82 (per-algorithm keyword
mute/boost), and #83 landed. Tracking-doc conflicts hand-resolved
(history/archive/roadmap/manual-actions/INSTALL.txt — both 2026-05-20
entries kept; my Condensed-history archive entries dropped in favour
of HEAD's already-condensed PR #77 entry). Code files
(`app/classifier/*`, `app/ranking.py`, `jobs/classify_pending.py`,
`seed/schema.sql`, `seed/feature_catalog.sql`, tests) auto-merged
cleanly — no overlap with the algo/feed/explain/style changes in the
upstream PRs.

### PR

- **PR #84** — Add 12 perceptual ranking features (draft 2026-05-20).
  Migration in `manual-actions.md` Open; apply before merge.

### Open items

- Apply `2026-05-20-perception-features.sql` on prod before merge
  (classify_pending errors on the missing columns from the first
  post-deploy tick).
- Doc-drift cleanup noticed but **not** fixed in this PR: `roadmap.md`
  still shows "Multiple saved algorithms / profiles" as `in-progress`
  even though it's merged on main and surfaced by `algo.html` (PR #65
  per Condensed history). PR #61 (stale draft) is a rework of the
  same feature. Worth a maintainer pass.

---

## 2026-05-20 — Per-algorithm keyword mute & boost (PR #82)

Roadmap "Per-algorithm keyword mute & boost (in the algo builder)"
(Pri 7 / LOE 3, algo/ui). User ask: "when building an algo, users
should be able to enter relevant keywords that they are interested in."
Extends PR #77's per-user `user_term_prefs` (still edited at `/terms`,
account-wide) with a parallel per-profile surface inside the algo
builder so different saved profiles can carry their own keyword intent
("Morning brief" boosts AI/local tech; "Weekend deep-dive" mutes
politics). `/terms` kept as the power-user account-wide surface; the
feed unions both lists.

### What shipped

- **New table `algorithm_term_prefs(algorithm_id, term, mode, weight)`**
  — same shape as `user_term_prefs` but FK'd to `user_algorithms`
  (`ON DELETE CASCADE` so deleting a profile removes its keywords).
  Migration `2026-05-20-algorithm-term-prefs.sql` + `seed/schema.sql`.
- **`app/routes/algo.py`** — two new routes (`POST /algo/keywords/add`,
  `POST /algo/keywords/<id>/delete`) reusing the shared
  `normalize_term` / `clamp_boost` helpers, the same 100-term cap as
  `/terms`, an ON-DUPLICATE-KEY upsert that moves a term between modes
  on re-add, and ownership-validated delete via a JOIN against
  `user_algorithms`. `_render_editor` now loads the active algorithm's
  mute/boost lists for the template.
- **`algo.html`** — new "Keywords" tab in the existing Alpine tab
  switcher (alongside UI / Code / Presets / Profiles); add form
  defaults to **boost** ("interested in" wording), profile-aware
  header shows which profile is being edited, link out to `/terms`
  for the global list. Append-only `.algo .add-keyword` / `.kw-*`
  block in `style.css` (no existing rule touched).
- **`app/routes/feed.py`** — `_active_weights()` now returns
  `(weights, active_algo_id)`. The signed-in term-prefs block reads
  `algorithm_term_prefs` for that id and **concatenates** the rows
  with `user_term_prefs` before calling `build_term_clauses`. The
  pure builder's existing dedupe + mute-wins rules carry the union
  semantics — mute at either scope drops the article, strongest
  boost on a term wins. No new helper, no ranking-formula change.
- **5 new pure tests** in `tests/test_term_prefs.py` pinning the
  cross-scope behavior (account-mute beats algo-boost on same term,
  algo-mute beats account-boost, distinct boost terms coexist,
  same-term boost dedupes to one clause). 22/22 green in-sandbox.

### Server-side state touched

- **One manual prod migration** (`manual-actions.md` Open, full
  inline SQL): `CREATE TABLE algorithm_term_prefs`. **BUG-007
  class** — the signed-in feed 500s on a missing table until applied
  (anon / `/firehose` / digest unaffected). Python App restart on
  deploy. No cron / env-var / pip / symlink change.

### Scope decisions (user-confirmed via AskUserQuestion up front)

- **Per-algorithm** (not per-user) — schema change accepted in
  exchange for per-profile intent.
- **Both mute and boost** in the embedded UI (not boost-only).
- **`/terms` kept** as a parallel power-user account-wide surface.

### Verification

`test_term_prefs.py` 22/22 in-sandbox; changed Python `py_compile`
clean; `algo.html` / `feed.html` Jinja-parse clean. Route + browser
UX deferred to CI / real env (no Flask/pymysql in sandbox —
documented limit).

### Rebase / conflicts

Rebased once mid-session onto `origin/main` after PRs #79 (Why This
Article explainer), #80, and #81 (compact toggle) landed. Two
append-only conflicts hand-resolved: `INSTALL.txt` (kept the new
"Why?" bullet from PR #79 and added the per-algo bullet underneath),
`style.css` (kept the `.why-*` block and appended `.algo .kw-*`).
`feed.py` auto-merged cleanly (PR #79 added an unrelated explainer
route; my edit lives in `index()`); `roadmap.md` auto-merged with no
duplicate rows or detail drift.

### PRs

- **PR #82** — Per-algorithm keyword mute & boost (merged 2026-05-20;
  `algorithm_term_prefs` migration applied on prod same day —
  `manual-actions.md` Completed).

### Open items / next session

- Tracking-doc drift surfaced (not addressed in this PR to avoid
  scope creep): `engineering-history.md` says *Multiple saved
  algorithms / profiles* merged as **PR #65**, but `roadmap.md`
  still lists it `in-progress` and a stale draft **PR #61** for the
  same feature is open. A small cleanup pass should move the
  roadmap row to Done and close PR #61.

---

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-20

- **Compact / density toggle (PR #81).** Pri 6 / LOE 2, ui. Techmeme-
  style toggle on the home feed: extends `base.html`'s existing
  dark-mode IIFE to also init `data-density` pre-stylesheet from
  `localStorage` (no FOUC); new `#density-toggle` button in the
  topnav. Append-only `style.css` block keyed on
  `:root[data-density="compact"] #feed-cards …` collapses to single
  column, tightens padding, hides `.thumb`/`.summary`/`.feature-bars`/
  `.byline` — source/lean dot/category/timestamp/`+N angles`/`Read →`
  all stay. Persistence per-device (no DB); scope `/` only. *Server:*
  none. Full detail: archive.

### 2026-05-18

- **Why This Article ranking explainer (PR #79).** Pri 7 / LOE 3, ui.
  "Why?" toggle on each feed card lazily loads an inline per-feature
  score breakdown for the viewer's active algorithm (anon → balanced).
  New pure `app/explain.py` reproduces `build_score_sql`'s per-feature
  term + recency gate in Python and **imports** the direction/scale
  helpers from `ranking.py` so the explainer can't desync from the
  scorer (18 parity tests). New `feed.explain` `GET /article/<id>/
  explain` partial with feed visibility scoping; HTMX progressive
  enhancement, no no-JS fallback; append-only dark-mode-aware CSS.
  *Server:* none — no DB/cron/dep/env/symlink. Per-user source/term
  multipliers applied outside the feature sum are deliberately not
  modeled in v1; learned-model line waits on Signal Learning. Full
  detail: archive.

### 2026-05-17

- **Keyword / topic mute & boost (PR #77).** Pri 8 / LOE 4, user-
  empowerment Theme A. Content-level lever distinct from
  `user_source_prefs` (whole-source weights): **mute** = hard filter,
  **boost** = score multiplier (strongest match wins, no compounding,
  term-in-both → mute wins). New Flask-free `app/term_prefs.py`
  builder (escaped LIKE, `GREATEST` boost — 17 pure tests, injection-
  proof); new `user_term_prefs` table + `/terms` blueprint + nav;
  `feed.py` reads it on every signed-in feed load and threads it
  through the `if u:` block. Scope = `/` feed, signed-in only
  (anon/firehose/digest untouched). v1 = substring match; phrase/
  entity-aware is v2. *Server:* `2026-05-17-term-prefs.sql`
  (`CREATE TABLE user_term_prefs`) applied on prod 2026-05-17 — folded
  into the load-bearing "Applied prod schema migrations" line above;
  BUG-007 class if absent. Full detail: archive.
- **BUG-020 firehose accumulation (PR #72).** `/firehose` was a
  refreshing snapshot — its 4s `innerHTML` poll replaced the table with
  only the newest ≤25 classified rows, dropping everything else. Now
  *accumulates*: stable `<tbody>`, poll prepends newer rows, "Load more"
  appends older, paginated by a new pure `app/firehose_cursor.py` keyset
  on `(classified_at, id)` (timestamp-only skipped same-second bursts —
  the real data-loss mechanism). 9 pure tests; no `style.css` change.
  *Server:* none. Full detail: archive / `bugs.md` BUG-020.
- **Across-the-spectrum in-feed (PR #69).** Pri 7 / LOE 3. The "+N
  angles" pill now **expands inline** to a few sibling outlets' coverage
  (round-robined across the lean spectrum, one per source) with a "Full
  dossier →" link, instead of navigating away. New pure
  `app/spectrum.py` (`pick_spectrum_sample`); `GET /story/<id>/peek`
  partial reusing the dossier's canonical+visibility fetch (extracted to
  `_fetch_cluster`); pill progressively enhanced (keeps `href` for
  no-JS). 10+5 tests. *Server:* none — no migration/cron/dep. Full
  detail: archive.
- **Full-text article search (PR #70).** Pri 6 / LOE 6. New `/search`
  route + nav box backed by a MySQL InnoDB FULLTEXT index on
  `articles(title, summary)` (NATURAL LANGUAGE MODE, query bound as a
  param — no injection). Results deduped by story cluster, scoped by the
  feed's source-visibility + per-user mute rules. *Server:*
  `2026-05-17-search-fulltext.sql` FULLTEXT ALTER applied on prod
  2026-05-17 (`manual-actions.md` → Completed); no cron/dep. Full
  detail: archive / INSTALL §10.
- **Trending topics view — /trending (PR #71).** Pri 7 / LOE 5. New
  `/trending` page ranking topics by distinct-outlet count, each
  linking to the dossier(s) under it. Conflict-free route (PR #56 was
  rewriting `classify_pending`): reuse the Google Trends/News topic
  index `trending_poll` already builds every 30 min — no LLM, no
  `classify_pending` edit. `trending_poll` now also rebuilds
  `trending_topics`/`trending_topic_articles` each tick (same txn as
  the `article_features.trending` scalar). Pure helpers in
  `app/trending.py` (+14 tests). *Server:* `trending_topics` +
  `trending_topic_articles` tables applied on prod 2026-05-17
  (`manual-actions.md` → Completed); no new cron/pip/env. Full detail:
  archive / INSTALL §8K/§10.
- **Multiple saved algorithms / profiles (PR #65).** User-empowerment
  Theme A (Pri 7). `user_algorithms` already had `name`/`is_active`,
  so app-layer only (**no migration**): `app/routes/algo.py` gains
  `_list_profiles`/`_set_active` (deactivate-all-then-activate-one —
  the single-active invariant every resolver depends on)/`_clean_name`
  + create/activate/rename/delete POSTs (delete refuses the last,
  promotes a survivor); `/algo` Profiles tab; feed-header `<select>`
  switcher at ≥2 profiles; appended `.profile-*` CSS.
  `save`/`use_preset`/`onboarding` behavior preserved. *Server:* none.
  Full detail: archive.
- **Dark mode (PR #63).** Client-only theme: `style.css` `:root`
  semantic surface vars (light values unchanged byte-for-byte) + a
  `:root[data-theme="dark"]` palette override with ~30 hardcoded
  literals repointed at vars; `base.html` no-FOUC head init from
  `localStorage.theme`/`prefers-color-scheme` + a nav toggle. *Server:*
  none (CSS/template only; restart on deploy). Full detail:
  `engineering-history-archive.md`.
- **Article save / bookmark (PR #64).** New `user_saves` table;
  `app/routes/saves.py` (`POST /save/<id>` toggle, `/save/<id>/read`,
  `GET /saved`); ☆/★ on signed-in cards via the `cardSignals` Alpine
  component; `maintenance.py` exempts saved articles from both
  retention prunes so the reader-view copy is a durable archive.
  *Server (applied 2026-05-17 post-merge, `manual-actions.md` →
  Completed; folded into "Applied prod schema migrations"; BUG-007
  recurrence — trailed the merge):* `2026-05-17-user-saves.sql`
  `CREATE TABLE`; restart. Full detail: `engineering-history-archive.md`.
- **Onboarding interview / cold-start (PR #62).** Upgraded the bare
  4-preset `/algo/onboarding` picker into a real cold-start interview:
  new Flask-free `app/onboarding.py` (`normalize_categories`,
  `lean_direction`, `build_onboarding_weights` layering
  `category_filter` + `political_lean_direction` onto the `balanced`
  preset, `top_trusted_sources`). `onboarding()` route now idempotent
  (redirects to editor if the user already has an algorithm), inserts
  one "My starting feed" `user_algorithms` row + `user_source_prefs`
  boosts (weight 1.5); signup redirects here. *Server:* none — no
  migration/cron/dep/env (`user_algorithms`/`user_source_prefs`
  already on prod). Full detail: `engineering-history-archive.md`.
- **Classifier/feature review — fixed BUG-016..019 (PR #56).**
  Review of the classifier/feature/ranking surface (11 findings, 4
  high fixed). BUG-016 popularity under-count (shared
  `popularity_score()`; `classify_pending` seeds from prior signals;
  nightly `maintenance` SQL reconciliation). BUG-017 journalist rep
  penalized bylined articles (`first_seen_at` from `published_at`;
  upside-only rep floor). BUG-018 `simhash==0` megacluster (skip
  branch when falsy; store NULL for 0). BUG-019 LLM-fallback
  contamination (`-nollm` version tag + bounded `_reclassify_nollm`
  heal). Code-only in cron scripts + a pure helper; full suite 245
  passing. *Server:* none — no migration/cron/env/pip/symlink; M/L
  review findings (M5–M8, L9–L11, perf) still open. Full detail:
  `engineering-history-archive.md`.
- **CSRF protection + auth rate limiting (PR #58).** Hand-rolled
  signed double-submit-cookie CSRF (stdlib `hmac`/`secrets`, zero new
  dependency) enforced app-wide on every unsafe-method route via
  `before_request`; token delivered to forms via `csrf_field()`, to
  HTMX via an `htmx:configRequest` header hook, to plain `fetch()`
  POSTs via a `<meta>` tag + `window.csrfToken`. `account.unsubscribe`
  exempt (RFC 8058 URL-token auth). `CSRF_ENABLED` config (conftest
  disables suite-wide; `test_csrf.py` re-enables). Sliding-window
  in-process rate limit on `/auth/login`+`/auth/signup` (10 POSTs/
  5 min/IP, env-tunable; per-worker caveat). *Server:* none — new env
  vars have working defaults; restart on deploy. Full detail:
  `engineering-history-archive.md`.
- **Natural-language algorithm builder + user-empowerment cluster (PR #59).**
  Plain-English feed description → one Claude Haiku call → the existing
  3-axis `FEATURES` weight vector, pre-filling the `/algo` editor for
  review (never applied silently; reuses `/save`, **no DB migration**).
  New Flask-free `app/algo_nl.py` (lazy `anthropic`, `LLMUnavailable`
  fail-soft, every value clamped, unknown keys dropped); `POST
  /algo/describe` re-renders the editor. Shipped with a 10-item
  user-empowerment roadmap cluster (themes A/B/C). No cron/env/dep/
  symlink change. Full detail: `engineering-history-archive.md`.
- **BUG-015 — external trending sort: Google Trends/News (PR #53).**
  Popularity sort was HN-only; added pure `app/trending.py` +
  `jobs/trending_poll.py` cron filling `article_features.trending`
  from Google Trends + Google News RSS. Renamed the `popularity`
  sort to **Trending** (`ORDER BY f.trending DESC, score DESC`;
  legacy `?sort=popularity` aliased). Opt-in `trending` FEATURES
  entry (default weight 0). *Server (applied 2026-05-17, `manual-actions.md` → Completed):* `2026-05-17-trending.sql` ALTER +
  a new every-30-min `trending_poll` cron; restart. Full detail:
  `engineering-history-archive.md` / `bugs.md` BUG-015.
- **Techmeme-style discussion links — Reddit/HN (PR #52).**
  `popularity_poll` already matched Reddit/HN threads but discarded
  the permalink; now persists `permalink`+`subreddit` on
  `popularity_signals` and renders a `Discussion: Hacker News (142)
  · r/tech (89)` line on feed cards + a story-dossier panel (pure
  `app/discussion.py`). No new dep/API cost. *Server (applied
  2026-05-17, `manual-actions.md` → Completed):* one nullable-column
  migration (`2026-05-17-discussion-links.sql`); restart.
- **Engineering-history archive process (PR #51).** Introduced the
  ~14K-token / ~34 KB budget for this file plus
  `engineering-history-archive.md` (verbatim, on-demand) and the
  durable "Load-bearing production state" section that never ages
  out. Procedure lives in `engineering-session-wrapup.md` Step 1b.
  Docs-only; no server-side change.
- **BUG-013 + BUG-014 — Latin-script filter via py3langid (PR #50).**
  Added stage 3 to `app/language.py is_english`: when text clears
  stages 1+2 and has ≥24 Latin letters, run a cached `py3langid`
  detector and reject only on a confident non-English call
  (`top_prob ≥ 0.85` AND `english_prob < 0.10`) — deliberately biased
  to keep English. Replaced the briefly-shipped `langdetect==1.0.9`
  (BUG-014: sdist-only, won't build on the cPanel venv) with
  wheel-distributed `py3langid==0.3.0` (+`numpy`); import fails soft
  so it's not a site-down risk. *Server:* `pip install -r
  requirements.txt` run on prod 2026-05-17 (no wheel build —
  `manual-actions.md` → Completed); no DB/cron/env-var change. Full
  detail: `bugs.md` BUG-013/014.

### 2026-05-14

- **Feed sort selector — Relevance / Newest / Popularity (PR #48).**
  `/?sort=` query param; `_normalize_sort` + `_order_by_for_sort`
  pure helpers in `feed.py` swap the ORDER BY (newest →
  `published_at`, popularity → `f.popularity`); threshold / source-
  pref / visibility filters unchanged; category tabs + Load-more
  preserve `sort=`. *Server:* none (restart on deploy).

### 2026-05-13

- **BUG-012 — refresh-shuffle via score jitter (PR #46).** Feed was
  deterministic so reloads showed the same top-30; added an opt-in
  `jitter` kwarg to `build_score_sql` wrapping the score in
  `* (1 + RAND()*jitter)`, live feed passes `FEED_JITTER` (default
  0.10); digest / firehose / algo-preview stay deterministic.
  *Server:* none; `FEED_JITTER` env-var has a working default. Full
  detail: `bugs.md` BUG-012.
- **English-only article filter at fetch time (PR #42).** Pure
  `app/language.py is_english(title,summary,feed_language)` — stage 1
  trusts a non-English feed `<language>` tag, stage 2 rejects when
  >25% of letters fall outside Latin script ranges; wired into
  `fetch_feeds` before insert with a `skipped_lang` counter. Existing
  non-English rows left to age out (no backfill purge). Known gap:
  Latin-script European content leaked through — later closed by
  BUG-013/014 (py3langid stage 3, PR #50). *Server:* none (cron
  picks up the new module on its next tick).
- **Story dossier v1 — `/story/<id>` (PR #43).** Multi-source view of a
  deduped story group across the lean spectrum; new `story_dossiers`
  table caches a Haiku framing summary keyed by member-signature,
  cost-gated to clusters with 3+ members and 2+ lean buckets; "+N
  angles" pill on multi-source feed cards. *Server:* `story_dossiers`
  migration; reuses the existing anthropic dep; restart post-merge.
- **Mobile / responsive polish (PR #40).** Single additive
  `@media (max-width:640px)` block + `.table-scroll` utility in
  `style.css`; desktop layout untouched. *Server:* none (CSS-only).
- **Automated source discovery — Reddit/HN + LLM agent (PR #38).** New
  `candidate_sources` table; 3 cron jobs (`discover_harvest` hourly,
  `discover_promote` nightly 04:00, `discover_llm` weekly Mon 05:00);
  `/admin/discovery` approve/reject/blacklist queue; pure helpers in
  `app/discovery.py`. *Server:* `candidate_sources` migration + the 3
  cron entries; no new pip dep.
- **BUG-011 — multiplicative recency gate (PR #34).** Ranking was
  additive so stale high-quality articles dominated forever; changed
  `recency` to a multiplicative freshness gate
  `score = quality * EXP(-r*h/24)` (`recency=0` = legacy behavior).
  *Server:* none; restart. Full root cause: `bugs.md` BUG-011.
- **BUG-010 — feature bars all rendered identically (PR #35).** Template
  wrote `style="width:NN%"` but `.feature-bars i` is a flex child and
  the CSS reads a `--w` custom property; switched to `style="--w:NN%"`.
  *Server:* none.
- **BUG-008/009 — classify_pending stalled prod (PR #32).** GoDaddy
  shared MySQL drops idle sockets during the long LLM/HTTP gap before
  the write block → added `conn.ping(reconnect=True)` at every idle
  point in `classify_pending` / `popularity_poll` / `fetch_feeds`;
  parallelized paywall + body HTTP via `ThreadPoolExecutor(10)`;
  `CLASSIFY_BUDGET_SECONDS` 90→240; throughput 10→180/tick. Lesson:
  ping-reconnect any cron that does HTTP between writes. *Server:* no
  schema change; `jobs/*.bak-*` on prod are stale (safe to delete).
  Full detail: `bugs.md` BUG-008/009.
- **BUG-007 recovery + wrap-up (PRs #30, #31).** Merged code referenced
  `sources.owner_id` + `user_source_prefs` before those migrations were
  run, 500'ing every reader route; ran them, restarted, drained the
  queue, confirmed prod schema synced, installed trafilatura.
  *Process learning:* treat `manual-actions.md` Open as a load-bearing
  blocker — run a migration before merging the next one. Full detail:
  `bugs.md` BUG-007.
- **Article deduplication across sources (PR #24).** `articles.simhash`
  + `articles.story_id` + `(story_id,published_at)` index; `fetch_feeds`
  computes a 64-bit SimHash and seeds `story_id=id`; `classify_pending`
  `_assign_story_id` clusters via exact `title_hash` or Hamming≤8 over a
  48h window, canonical = highest `source_reputation`; feed dedupes by
  `story_id`, firehose stays un-deduped; `maintenance` heals orphans.
  Heavy paraphrase not clustered (v2 = embeddings). *Server:* dedup
  migration; restart.
- **Manual-actions tracker (PR #22).** Added `manual-actions.md`
  (Open/Completed, full SQL inline) + the session-start/wrap-up
  lifecycle hooks. *Server:* none.
- **User-added RSS feed subscriptions (PR #29).** `/sources` page;
  signed-in users add personal feeds scoped by `sources.owner_id`;
  feed/firehose visibility filter; `app/feed_validation.py`. *Server:*
  `sources.owner_id` migration.
- **In-app reader view + body extraction (PR #21).** `article_bodies`
  table; `app/extractor.py` (lazy `trafilatura`, 1 MB cap,
  `MIN_WORDS=60`) wired into `classify_pending` (paywall-aware, shares
  the cron wallclock budget); `/read/<id>` + reader template; nightly
  `BODY_RETENTION_DAYS` prune. *Server:* `article_bodies` migration +
  `pip install` (trafilatura); restart.
- **Thumbs up/down + signal foundation (PR #19).** Generic
  `user_signals` table (forward-compat for Signal Learning) +
  `user_source_prefs`; `/signal` blueprint (toggle thumbs,
  3-downs-from-source prompt); feed query splices the per-user-source
  weight. *Server:* signals migration.
- **Daily personalized email digest (PR #23).** Opt-in
  `users.digest_enabled` + unsub token; noon-UTC `send_digest` cron
  reusing the feed ranking SQL; stdlib `smtplib` (localhost MTA by
  default; `SMTP_*` env vars for a real relay). *Server:* digest
  migration + the noon-UTC cron; optional `SMTP_*` env vars.
- **Cron hardening + PyMySQL timeouts (PR #15).** `job_lock(name)`
  fcntl mutex in `_bootstrap.py` wrapping each `main()`; `requests`
  timeouts on RSS/Reddit/HN; anthropic `timeout=30`; PyMySQL timeouts
  (web `(5,15,10)`, cron `(5,30,15)`); `FEED_FETCH_BATCH` 80→20.
  *Server:* none; restart; lockfiles appear in `news/logs/`.

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
