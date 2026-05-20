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
tick). A DB rebuild from `seed/schema.sql`
already includes these.

---

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-20

- **Per-profile "Publish to gallery" button (PR #94).** Small UX
  follow-on to PR #88: each row in `/algo` Profiles tab now carries
  a "Publish to gallery" form that snapshots that specific profile.
  `gallery.publish` accepts an optional `algo_id` form param
  (ownership-checked), falls back to the active profile when
  absent — so the gallery page's existing details form keeps
  working unchanged. Same cap/sanitization/redirect. *Server:* none.
- **Gallery — Copy link + Email share buttons (PR #95, merged 2026-05-20).**
  Tiny follow-on to PR #88. Each `/gallery` card now has **Copy link**
  (writes a permalink to clipboard via `navigator.clipboard.writeText`,
  falls back to `window.prompt` on non-secure contexts) and **Email**
  (`<a href="mailto:?subject=…&body=…">`, no JS needed) next to
  Adopt/Unpublish. Permalink =
  `url_for('gallery.index', _external=True) ~ '#listing-<id>'`; each
  card carries `id="listing-<id>"` + a `:target` CSS rule that
  highlights the card when followed. Jinja `|urlencode` handles
  spaces/newlines/`&`/`#` in the mailto body. Available to anonymous
  viewers too. Template + CSS only — no route, DB, migration, cron,
  env, or pip dep. *Server:* none (Python App restart on deploy for
  the new template/CSS to load, but Jinja autoreloads templates).
- **Source catalog admin re-import on prod (PR #91 follow-up).** User
  ran the `/admin/feeds` → "Re-import seed CSV" action on prod
  2026-05-20 (idempotent upsert on `feed_url`), loading the +1151
  new sources from `seed/source_lean.csv` (768 → 1919). Dead URLs
  will self-deactivate at `error_count=10` over the next few days.
  `manual-actions.md` entry moved to Completed.
- **Shareable algorithm gallery v1 (PR #88).** Pri 8 / LOE 6,
  new-feature/ui (theme C keystone). User: "an algorithm library
  where users can pick and use other people's algos" with filterable
  usage stats. Minimal v1 scope (publish / browse / adopt; admin-only
  DB takedown — no public reporting UI). Three usage stats double as
  sort axes: total adoptions, last-7d, active (distinct users whose
  cloned profile still exists; the `ON DELETE SET NULL` on
  `algorithm_adoptions.user_algorithm_id` is what makes "active"
  self-maintain without a reconciliation job). New pure `app/gallery.py`
  (`sort_order_by` is a closed literal map → no SQL-injection via
  `?sort=`; `escape_like` for `?q=`), new `/gallery` blueprint
  (publish / adopt / unpublish), template + append-only `.gallery-*`
  CSS, one nav link. Adopt = clone-into-a-new-active-profile (atomic
  clear-all-then-set, mirrors `algo._set_active`); preserves existing
  profiles. 11 pure tests + a `"; DROP TABLE"` guard on the sort
  fragment. *Server:* `2026-05-20-shared-algorithms.sql`
  (`shared_algorithms` + `algorithm_adoptions`) applied on prod
  2026-05-20 (`manual-actions.md` → Completed). NOT BUG-007 class —
  tables are read-only at feed time, so a missing migration only
  500s `/gallery` itself. Full detail: archive.
- **Source catalog expansion +1151 sources (PR #91).** Pri 7 / LOE 3,
  ops/new-feature. Appended 1151 hand-curated high-quality sources to
  `seed/source_lean.csv` (768 → 1919). ~630 institutional outlets (US
  regional papers, state-capital press, States-Newsroom nonprofits, NPR
  affiliates, trade pubs, magazines, think tanks; intl — UK/EU/LATAM/
  Africa/MENA/Asia-Pacific). ~520 individual writers / Substacks /
  Medium / engineering blogs (Stratechery, Platformer, Slow Boring,
  HCR, Money Stuff, Marginal Revolution, Volts, Heatmap, Latent Space,
  Karpathy, Simon Willison, Sinocism, ChinaTalk, Le Grand Continent,
  corporate eng blogs from Netflix/Stripe/Cloudflare/GitHub/OpenAI/
  Anthropic/HuggingFace/BAIR). 47+ countries; US share 69%; honest
  source_lean -0.5..+0.5, reputation 0.66–0.92. 0 dup `feed_url`. No
  code change. *Server:* one Open `manual-actions.md` entry —
  admin clicks "Re-import seed CSV" on `/admin/feeds` (idempotent
  upsert; no migration, no cron change, no restart). Dead/wrong URLs
  self-deactivate via the PR #11 `error_count=10` gate (~5–15%
  expected tail). Full detail: archive.
- **BUG-021 single-source feed domination (per-source cap, PR #89).**
  User-reported "weird recency bias" — the `/` feed showed mostly
  Philadelphia Inquirer under different algorithms. Root cause: no
  per-source diversification; feed dedup was per-`story_id` only, so
  a source with a fetch burst (or high `source_reputation` × BUG-011
  recency multiplier hitting many rows) legitimately swept all 30
  slots until ~24h decay broke it up. Fix: new pure
  `app/feed_diversify.py` (`cap_per_source` / `fetch_budget` /
  `page_slice`); `feed.py index()` over-fetches, caps in Python AFTER
  the existing ORDER BY (preserving rank within source), then slices
  the page. New `FEED_MAX_PER_SOURCE` config (default 3,
  env-tunable; 0 disables — kill-switch w/o deploy). `/` only;
  `/firehose`/`/search`/`/saved`/digest unchanged. 14 pure tests.
  *Server:* none. Full detail: archive / `bugs.md` BUG-021. PRs #87
  (BUG-021 log) + #89 (fix).
- **Perceptual feature expansion — 12 new ranking features (PR #84).**
  Roadmap Pri 7 / LOE 5, algo/backend. Doubled `FEATURES` (12→24):
  6 LLM-judged (`tone_calmness`, `sensationalism`, `analysis_depth`,
  `emotional_charge`, `hedging`, `solution_orientation`) batched into
  the existing `classify_pending` Haiku call (one extra JSON object
  per article, ~3× prior per-article LLM cost, still
  sub-$0.001/article) + 6 rule-based (`headline_length`, `caps_ratio`,
  `punctuation_intensity`, `numeric_density`, `question_headline`,
  `quote_present`) computed in `app/classifier/rules.py` with no
  network/LLM. LLM-unavailable rows get 0.5 across the 6 perceptual
  ones; `_reclassify_nollm` heals them. Existing user algos
  unaffected — their `weights_json` doesn't reference the new keys,
  `build_score_sql` skips them until a user opts in via /algo
  (template loop auto-renders the 12 new sliders). 21 new pure tests.
  *Server:* `2026-05-20-perception-features.sql` (12 ADD COLUMN + 12
  feature_catalog INSERT) applied on prod 2026-05-20
  (`manual-actions.md` → Completed; folded into the load-bearing
  "Applied prod schema migrations" line above); BUG-007 class
  (`classify_pending` writes the new columns every 5-min tick;
  Python App restart required to load the updated `FEATURES`
  catalog). Full detail: archive.
- **Per-algorithm keyword mute & boost (PR #82).** Pri 7 / LOE 3,
  algo/ui. Extends PR #77's per-user `user_term_prefs` with a parallel
  **per-profile** surface inside the `/algo` builder: new
  `algorithm_term_prefs(algorithm_id, term, mode, weight)` table FK'd
  to `user_algorithms` (CASCADE), two new `POST /algo/keywords/*`
  routes (ownership-validated, 100/profile cap, mode-move upsert),
  new "Keywords" tab in the algo Alpine switcher. `routes/feed.py`
  reads both tables for the active profile and unions the rows
  through the existing pure `build_term_clauses` builder — mute at
  EITHER scope wins, strongest matching boost wins. 5 new cross-scope
  tests. Same v1 substring caveat as PR #77; same scope (signed-in
  main feed only; anon/firehose/digest untouched). *Server:*
  `2026-05-20-algorithm-term-prefs.sql` (CREATE TABLE) applied on
  prod 2026-05-20 (`manual-actions.md` → Completed; folded into the
  load-bearing "Applied prod schema migrations" line above); BUG-007
  class if absent. Full detail: archive.
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
