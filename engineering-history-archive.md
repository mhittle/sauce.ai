# sauce.ai/news — Engineering history (archive)

Verbatim historical record. Entries here were moved out of
`engineering-history.md` when that file exceeded its ~14K-token ingestion
budget (see `engineering-session-wrapup.md` → "Archive
`engineering-history.md`").

**Not read during normal onboarding.** Consult this file only when
troubleshooting a regression or when you need the deeper context behind a
condensed entry (root causes, calibration notes, file lists). It is large
— grep for a PR number, BUG-ID, or date and read that section with
`offset`/`limit`; do not read it end-to-end.

Newest-first, same heading format as the live file. The live file's
"Condensed history" section maps each one-paragraph summary back to the
full entry here. Not-in-repo server state from these entries is
consolidated into the durable "Load-bearing production state" section of
the live file — that section, not this archive, is the source of truth
for current prod state.

---

## Condensed-in-bulk on 2026-05-21 — verbatim 2026-05-20 + 2026-05-17 live entries

These dated sections were moved here verbatim when the live
`engineering-history.md` was condensed on 2026-05-21 (it had grown
past its single-read budget). The live file keeps one-line summaries
of each; load-bearing prod state is in the live file's "Load-bearing production state" section.

### 2026-05-20

- **Lab landing expansion — 10 more radical concepts + anon up/down
  voting (PR drafted this session).** Roadmap Pri 6 / LOE 3,
  ui/new-feature/backend. User on PR #101 (merged earlier this
  session): "These ideas are kind of mid. Add some more radical
  consumer-focused concepts, like jar.ai and other high&#8209;leverage
  tools for people. Add another 10 concepts to this along with a way
  to vote them up or down." Two coupled changes:
  - **+10 concepts.** Total card grid is now 1 live + 17 coming&#8209;soon.
    New keys, ordered radical-first: `jar` (AI memory jar / second
    brain), `negotiate` (success-fee bill negotiator), `doctor`
    (calibrated health triage), `legal` (contracts / leases / small
    claims), `clone` (your voice + reasoning, trained), `tax`
    (year&#8209;round agent), `decide` (big&#8209;call structurer),
    `friend` (relationship&#8209;maintenance nudger), `estate`
    (wills + digital legacy), `mirror` (weekly self&#8209;debrief).
    Re-ordered the 7 first&#8209;wave concepts after the new wave so
    the radical picks lead.
  - **Anonymous voting.** Each coming&#8209;soon card now has ▲/▼
    buttons and an HN&#8209;style net score, populated from a new
    Flask endpoint on the news app (`GET /news/labvotes/tally`,
    `POST /news/labvotes/vote`). Anon identity is a 40&#8209;hex
    token in a `lab_voter_token` cookie set by the tally response
    with `Path=/`, so the static root page (`sauce.ai/`) and the
    news app (`sauce.ai/news/`) share the same voter token (same
    host). Optimistic UI, error&#8209;tolerant (a 500 from the API
    hides the vote bars and leaves the cards otherwise rendered).
  *Code:* new pure `app/lab_concepts.py` (concept&#8209;key allowlist
  + `normalize_vote` + `is_valid_voter_token` + `tally_with_you`),
  new `app/routes/lab.py` blueprint (no auth, no CSRF — added to
  `_EXEMPT_ENDPOINTS` next to `account.unsubscribe`; rationale is
  symmetric — anon endpoint, low&#8209;stakes, per&#8209;voter
  UNIQUE index caps abuse from any one cookie), blueprint registered
  in `app/__init__.py`, root `index.html` rewritten (18 cards +
  ~50&#8209;line vanilla&#8209;JS voting handler, no framework, no
  extra HTTP request), `seed/schema.sql` appended,
  `seed/migrations/2026-05-20-lab-votes.sql` new, 12 new pure tests
  in `tests/test_lab_concepts.py` (12/12 pass in sandbox).
  *Server:* one Open `manual-actions.md` entry —
  `2026-05-20-lab-votes.sql`: `CREATE TABLE lab_concept_votes`. **Not
  BUG-007 class:** only the `/labvotes/*` endpoints touch the table;
  the rest of the news app is unaffected, and the landing page
  catches a tally fetch error and hides the vote UI silently if the
  migration is missing — so the cards still render. Python App
  restart on deploy so the new blueprint registers. Schema.sql + the
  load-bearing "Applied prod schema migrations" line updated.
- **Root sauce.ai/ landing page (product-lab positioning, PR drafted
  this session).** Roadmap Pri 6 / LOE 1, ui/ops/docs. User: "the root
  site of sauce.ai will state that sauce.ai is an autonomous ai product
  development and engineering lab... the first product is Sauce.ai
  news. Make a few other cards for consumer products that we could
  start to autonomously engineer next." Until now the repo root carried
  no HTML — anything at `https://sauce.ai/` was a cPanel default. The
  existing GitHub Actions FTP workflow (`local-dir: ./`,
  `server-dir: /`, `dangerous-clean-slate: false`, FTP user
  `sauce@sauce.ai` → `~/public_html/sauce.ai/`) already publishes
  whatever's at the repo root, so a single new `index.html` is enough.
  *Code:* one new file, `/index.html` — self-contained (inline CSS, no
  framework, no extra HTTP request, no build step); matches the news
  app's editorial-serif wordmark (`ui-serif` family, italic for the
  product noun) and warm-neutral palette (`--bg #fafaf7`, surfaces,
  same accent feel); `prefers-color-scheme: dark` handles dark theme
  with no JS toggle in v1 (news has its own toggle on its subdomain
  surface). Hero states the thesis; 8-card grid: 1 live card
  (`sauce.ai/news`, links to `/news`, "Live" badge) plus 7 "Coming
  soon" concepts — Recipes (taste-aware meal planner), Travel (vibe →
  bookable itinerary), Money (personal CFO), Fit (wearable-aware
  coach), Learn (30-min daily course generator), Inbox (voice-matching
  triage), Stage (live music/theatre/comedy radar). Footer: "built by
  agents, supervised by humans" — owns the thesis. *Server:* none — no
  migration, no cron, no env var, no pip dep, no symlink, no Python
  App restart needed. **Deploy caveat:** on first push to `main`, the
  FTP sync will *overwrite* whatever `index.html` currently lives at
  `~/public_html/sauce.ai/index.html` (cPanel default or prior
  placeholder). The news app at `/news` is untouched (separate dir,
  separate `.htaccess`).
- **Keywords-on-algo only — drop /terms, travel with gallery publish/adopt
  (PR drafted).** Pri 6 / LOE 3, algo/ui/new-feature. User: "keywords
  should be part of each algo." Two coupled changes:
  - **Account-wide `/terms` surface removed.** Deleted
    `app/routes/term_prefs.py` + `templates/me_terms.html`,
    unregistered the blueprint, dropped the "Your Keywords" nav link.
    `routes/feed.py` no longer SELECTs `user_term_prefs`; the term-row
    list is only `algorithm_term_prefs` for the active profile. Pure
    `app/term_prefs.py` builder stays (still the SQL fragment-maker for
    the algo-scoped path); docstring rewritten to drop the "per-user"
    framing, and the 5 obsolete "union" tests in
    `test_term_prefs.py` were removed.
  - **Gallery publish/adopt carry keywords.** New
    `shared_algorithms.keywords_json TEXT NOT NULL` column;
    `gallery.publish()` snapshots the algorithm's
    `algorithm_term_prefs` rows into it; `gallery.adopt()` parses the
    snapshot and inserts the rows into the cloned profile's
    `algorithm_term_prefs`. New pure helpers `snapshot_keywords` /
    `parse_keywords` in `app/gallery.py` sanitize through
    `normalize_term` / `clamp_boost` / `VALID_MODES` so an untrusted
    listing (a publisher could hand-craft `keywords_json`) cannot
    poison the adopter's keyword table. 100-keyword snapshot cap. 8
    new tests in `test_gallery.py` (cap, sanitization, round-trip,
    malformed-blob rejection).
  *Server:* one Open `manual-actions.md` entry (BUG-007 class) —
  `2026-05-20-keywords-on-algo.sql`: (1) `INSERT IGNORE INTO
  algorithm_term_prefs ... FROM user_term_prefs JOIN user_algorithms
  ON is_active=1` to preserve existing /terms data on each user's
  active profile; (2) `ALTER TABLE shared_algorithms ADD COLUMN
  keywords_json TEXT NULL → backfill '[]' → MODIFY NOT NULL` (the
  nullable-then-tighten pattern avoids the strict-mode rejection of a
  NOT NULL TEXT ADD COLUMN on a populated table); (3) `DROP TABLE
  user_term_prefs`. Python App restart on deploy. Schema.sql + the
  load-bearing "Applied prod schema migrations" line updated.
- **`.gitattributes` `merge=union` for high-conflict tracking docs.**
  Ad-hoc / infra. User pain point: every parallel session appends to
  `engineering-history.md` at the same top-of-log anchor, forcing a
  manual conflict resolution on every rebase. Added `.gitattributes`
  marking `engineering-history.md` + `engineering-history-archive.md` +
  `roadmap.md` + `bugs.md` + `manual-actions.md` `merge=union` so Git
  auto-takes both sides instead of failing the rebase. Trade-off (now
  explicit in `new-engineering-session-instructions.md` §7.4):
  out-of-order dated headers and duplicate at-a-glance rows can appear
  after a union merge and must be cleaned up in the same PR — but the
  rebase no longer *blocks* on these files. Docs-only; no
  server/cron/dep/migration change.
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
- **BUG-022 topnav text overflows page width (PR pending).** User
  reported the topnav extended past the main page. Root cause:
  `.topnav` had `font-size:1em` + `gap:1.2em` + no `flex-wrap` on
  desktop; signed-in users carry ~10 links + a 14em search box +
  Compact/Dark toggles, so the row ran off the right edge instead of
  wrapping. Fix: shrink `.topnav` to `font-size:0.88em`, tighten
  `gap` to `0.9em`, add `flex-wrap:wrap`; bump brand to `1.15em` so
  the wordmark stays a touch larger than the link row (net absolute
  brand size roughly unchanged). Mobile `@media (max-width:640px)`
  overrides still win below that breakpoint. *Server:* none — CSS-
  only; restart on deploy. Full detail: `bugs.md` BUG-022.
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

---

## 2026-05-20 — Shareable algorithm gallery v1 (PR #88)

Migration `2026-05-20-shared-algorithms.sql` applied on prod 2026-05-20
(user-confirmed; `manual-actions.md` → Completed). `/gallery` is live.

Roadmap **Pri 8 / LOE 6 — "Shareable algorithm gallery"** (theme C
keystone). User: "an algorithm library where users can pick and use
other people's algos" with filterable usage stats. v1 scope chosen
via AskUserQuestion: **Minimal** (publish / browse / adopt; no
reporting UI, no admin moderation queue — takedowns are admin-only
via DB). Three v1 usage stats double as sort axes: total adoptions,
last-7d adoptions, active adoptions (distinct users whose cloned
profile still exists).

### What shipped

- **`app/gallery.py`** (new, Flask-free / DB-free, mirrors
  `app/term_prefs.py`): `clean_listing_name`, `clean_description`,
  `normalize_sort` + `sort_order_by` (closed literal map — no
  SQL-injection surface via `?sort=`), `normalize_search`,
  `escape_like`. 11 pure tests in `tests/test_gallery.py` (incl. a
  `"; DROP TABLE"` guard on the sort fragment).
- **`app/routes/gallery.py`** (new blueprint at `/gallery`):
  `GET /` list with `?sort=` (popular / trending / active / newest)
  + `?q=` substring filter; `POST /publish` snapshots the active
  algo (per-user cap 20); `POST /<id>/adopt` atomic
  clear-all-then-set into a new active `user_algorithms` row + one
  `algorithm_adoptions` event row; `POST /<id>/unpublish`
  owner-only delete (adoption rows cascade-delete with the listing,
  adopters' cloned profiles persist).
- **`app/templates/gallery.html`** + append-only `.gallery-*` CSS:
  cards show 3 stats, optional description, top-3 weights summary,
  "Yours" / "Adopted" badges; anon gets a sign-in CTA.
- **`app/__init__.py`** blueprint registration; **`base.html`** one
  nav link between Firehose and search.

### Server-side state

**New tables — load-bearing for `/gallery` only.** `shared_algorithms`
+ `algorithm_adoptions`; **not** read at feed time, so a missing
migration 500s ONLY `/gallery` (not BUG-007 class). Applied on prod
2026-05-20. `ON DELETE SET NULL` on
`algorithm_adoptions.user_algorithm_id` is the trick that makes
"active count" work without a reconciliation job — when an adopter
deletes their cloned profile the row stays for total / 7d counts but
drops out of active. No cron / env / pip / symlink. Python App
restart on deploy.

### Verification + rebases

`tests/test_gallery.py` 11/11 + `test_ranking.py` green in-sandbox;
`.py` `py_compile` clean; templates Jinja-parse. Route + DB behavior
deferred to CI / browser. Rebased four times as PRs #82, #84,
#85/#86/#87, #89/#91 landed in parallel — only append-only conflicts
in tracking docs + INSTALL.txt + style.css; gallery touches no
classifier/ranking/algo/feed code, so `.py` files auto-merged.

### PR

- **PR #88** — Shareable algorithm gallery v1 (draft).

---

## 2026-05-20 — Source catalog expansion (+1151 sources) (PR #91)

User-requested: 1000 more high-quality sources, including Substack /
Medium individual writers. Scope confirmed via `AskUserQuestion`:
50/50 outlets/individuals, ~65% US / ~35% intl, single PR appending
to `seed/source_lean.csv` (vs. the candidate_sources review queue).

### What shipped

- **`seed/source_lean.csv`**: 768 → 1919 (+1151 unique rows). ~630
  institutional outlets (US regional / state-capital papers across all
  50 states; States-Newsroom + local investigative nonprofits; NPR
  affiliates; trade pubs — Stat News, Defense One, etc.; magazines —
  Atlantic subsections, Foreign Affairs, Lawfare, NY Mag, NYRB, LRB;
  think tanks — Brookings/AEI/Cato/CFR/CSIS/Chatham/RUSI; intl —
  Le Monde, Mediapart, Spiegel International, Politico Europe, Kyiv
  Independent, Meduza, Bellingcat, Asahi, Nikkei, Caixin, HKFP, Daily
  Maverick, Premium Times, Animal Político, El Faro, Haaretz). ~520
  individuals — Stratechery, Platformer, Slow Boring, HCR, Money Stuff
  (Bloomberg author RSS), Marginal Revolution, Construction Physics,
  Works in Progress, Apricitas, Adam Tooze, YLE, Volts, Heatmap,
  Latent Space, Karpathy, Simon Willison, Pluralistic, Schneier;
  corporate eng blogs (Netflix Tech, Stripe, Cloudflare, GitHub,
  OpenAI, Anthropic, HuggingFace, BAIR); intl analysis (Sinocism,
  ChinaTalk, Phillips O'Brien, Le Grand Continent, Le Monde
  Diplomatique). Lean -0.5..+0.5 honestly; reputation 0.66–0.92.
- **Distribution**: 47+ countries; US 69% (target 65%); GB 7%, others
  small. Categories: general 412 / politics 282 / tech 161 / world 122
  / business 101 / science 68 / sports 5.
- **`roadmap.md`**: new Done entry + at-a-glance row (Pri 7/LOE 3,
  ops/new-feature).
- **`manual-actions.md`**: Open entry — admin clicks `Re-import seed
  CSV` on `/admin/feeds` (idempotent `feed_url` upsert, no schema
  change).

### Server-side state touched

None **yet** — one queued manual action. No DB migration, no cron
change, no env var, no pip install, no symlink. `fetch_feeds` picks up
new `sources` rows on its next 15-min tick once the admin import runs;
dead/wrong URLs self-deactivate at `error_count=10` via the PR #11
auto-deactivate logic, so no hand-cleanup needed for the inevitable
dead-feed tail (~5–15% expected from training-memory URLs).

### Verification

- 0 duplicate `feed_url` rows in final CSV; all 1920 lines have 8
  fields; all `source_lean` in [-1,1] and `source_reputation` in
  [0,1]; all URLs start `http(s)://` (Python validation: 0 problems).
- 1411 drafted → 209 dropped vs existing → 51 dropped as internal
  dupes → 1151 net unique added.
- Live import + per-feed validity deferred to maintainer / cron
  (sandbox has no admin session; ~115 feed-URL guesses from training
  memory will fail at first fetch — auto-deactivate handles).

### Known v1 caveats

- Expect ~5–15% dead-feed tail (e.g., Arc Publishing `/arc/outbound
  feeds/rss/` URL patterns vary across McClatchy/Tribune/Hearst
  papers); cron auto-deactivates at error_count=10.
- A handful of engineering corporate blogs (Netflix Tech, Stripe
  Blog) sit in `tech` and aren't strictly journalism; intentional for
  the tech-heavy-algo audience, downweightable per-user via
  `/sources`.
- Per-source body-extractor tuning (`trafilatura`) is generic v1 path
  — paywalled / JS-heavy new sources may show short summaries.

### PR

- **PR #91** — Source catalog expansion (+1151 sources) (merged
  2026-05-20). Admin re-import on prod still **Open** in
  `manual-actions.md`.

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

- **PR #84** — Add 12 perceptual ranking features (merged 2026-05-20).
  Migration `2026-05-20-perception-features.sql` applied on prod
  2026-05-20 (`manual-actions.md` → Completed).

### Open items / next session

- Doc-drift noticed but **not** fixed here: `roadmap.md` still shows
  "Multiple saved algorithms / profiles" as `in-progress` even though
  it's merged on main and surfaced by `algo.html` (PR #65 per
  Condensed history); stale draft PR #61 for the same feature.
  Maintainer cleanup pass.

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

## 2026-05-20 — Compact / density toggle (PR #81)

User-requested mid-session: a Techmeme-style density toggle that strips
images and chrome from the home feed.

### What shipped

- **`base.html`**: extended the existing `<head>` IIFE to also read
  `localStorage.density` and set `data-density="compact"` on `<html>`
  pre-stylesheet (no FOUC, mirrors the dark-mode init from PR #63). New
  `<button id="density-toggle">` in the topnav next to `theme-toggle`;
  paired click-handler IIFE flips the attribute + writes localStorage
  + syncs `Compact ↔ Comfortable` label and `aria-pressed`.
- **`style.css`**: appended `:root[data-density="compact"] #feed-cards …`
  block — collapses the grid to single-column, tightens card padding,
  hides `.thumb` / `.summary` / `.feature-bars` / `.byline`. Source,
  lean dot, category, timestamp, thumbs/save, `+N angles`, `Read →`,
  discussion line, and the auto-hide-when-empty `.spectrum-peek` all
  stay.
- **`roadmap.md`**: new "Compact / density toggle (Techmeme-style)"
  entry (Pri 6 / LOE 2, ui), status `in-progress`.

### Scope choices (user-confirmed via AskUserQuestion at session start)

- **Persistence = localStorage only** (per-device, no DB). Matches
  dark-mode exactly — lowest-conflict path for parallel sessions.
- **Scope = home feed `/` only**. CSS is keyed on `#feed-cards` (unique
  to `feed.html`), so `/search`, `/saved`, `/firehose` are deliberately
  untouched. Future expansion to those pages is just removing the
  `#feed-cards` prefix.
- Toggle button itself is **global in the topnav** (mirrors the
  dark-mode toggle UX); flipping it from a non-`/` page just primes the
  preference for the next visit to `/`.

### Server-side state touched

None. No DB / cron / env / pip / symlink change. **No `manual-actions.md`
entry.** Standard Python App restart on deploy.

### Verification

`base.html`, `feed.html`, `partials/feed_cards.html` Jinja-parse clean.
Sandbox lacks pytest (documented limit) but no Python changed — there
is no test surface. Real-env / browser verification deferred to CI /
maintainer: toggle flips label + persists; compact mode strips
image/feature-bars/summary/byline on `/`; other pages unaffected; HTMX
"Load more" rows honor compact via global CSS; `+N angles` still
expands `.spectrum-peek` inline.

### PR

- **PR #81** — Compact / density toggle (draft, branch
  `claude/onboard-news-aggregator-ReNpA`).

### Doc-drift noted during onboarding (not in this PR)

- Roadmap still marks **"Multiple saved algorithms / profiles"** as
  `in-progress` though `engineering-history.md` Condensed history
  records it as shipped in **PR #65** (app-layer only). Open draft
  **PR #61** implements the same feature from a separate older session
  and is very likely superseded — flagged to the user; left alone here.

---

## 2026-05-18 — Why This Article: ranking explainer (PR #79)

Roadmap Pri 7 / LOE 3 (ui). A "Why?" toggle on each feed card lazily
expands an inline per-feature score breakdown for the viewer's active
algorithm.

### What shipped

- **`app/explain.py`** (new, pure/Flask-free/DB-free, mirrors
  `spectrum.py`): reproduces `build_score_sql`'s per-feature term
  `w*(1-|v-d|/scale)` + the `exp(-w·h/24)` recency gate in Python.
  Imports `_direction_from_weights`/`_scale_width` **from `ranking.py`**
  (not re-derived) so the explainer can't desync from the scorer —
  parity is the whole point. 18 pure tests `tests/test_explain.py`.
- **`feed.explain`** `GET /article/<id>/explain` → `partials/
  why_panel.html`; same `_active_weights` + `sources.owner_id`
  visibility scoping as the feed (anon → balanced default), 404 on
  unknown/unclassified/hidden.
- **`feed_cards.html`**: progressive-enhancement HTMX trigger (GET, no
  CSRF) + per-card `#why-<id>` container; `style.css` append-only
  `.why-*` block, dark-mode-aware via semantic vars (no existing rule
  touched). INSTALL §10 limit note; roadmap → in-progress.

### Server-side state touched

None. No DB/cron/env/pip/symlink. Python App restart on deploy so the
new route + partial load. **No `manual-actions.md` entry.**

### Verification

`test_explain` 18/18 + `test_ranking`/`test_spectrum` green via the
sandbox driver (no pytest/Flask in sandbox — documented limit);
changed Python `py_compile` clean, templates Jinja-parse. Route/browser
deferred to CI/real env. Scope: feature contributions + recency only
(per-user source/term multipliers applied outside the feature sum are
not modeled); the learned-model line waits on Signal Learning.

### PR

- **PR #79** — Why This Article ranking explainer (merged 2026-05-18).

---

## 2026-05-17 — Keyword / topic mute & boost (PR #77)

Roadmap Pri 8 / LOE 4 (algo, ui), user-empowerment cluster theme A.
Content-level lever distinct from `user_source_prefs` (whole-source
weights): **mute** = hard filter, **boost** = score multiplier.

### What shipped

- **`app/term_prefs.py`** (new, Flask-free, mirrors
  `app/discussion.py` — pure, tested like `build_filters_sql`):
  `normalize_term`, `clamp_boost` ([1.0,5.0], def 1.5), `escape_like`,
  `build_term_clauses` → `(mute_sql, boost_expr, params)`. Mute = ANDed
  `NOT (<title+summary> LIKE %term% ESCAPE …)`; boost =
  `GREATEST(1.0, CASE WHEN … THEN w ELSE 0 END, …)` (strongest match
  wins, no compounding); term-in-both → mute wins; always
  parameterized.
- **`user_term_prefs`** table (`UNIQUE(user_id,term)` → one mode/term)
  + `seed/schema.sql` + `2026-05-17-term-prefs.sql`. New blueprint
  `/terms` (mirrors `routes/sources.py`: list/add-upsert/delete,
  100-term cap, `@login_required`), `me_terms.html`, nav link.
- **`app/routes/feed.py`**: existing signed-in `if u:` block gains one
  `user_term_prefs` read → boost multiplies score beside
  `pref_score_mult`, mute appended to WHERE. Scope = `/` feed,
  signed-in only (anon/firehose/digest untouched — `user_source_prefs`
  parity; limits BUG-007 blast radius).
- **`tests/test_term_prefs.py`** (17 pure); INSTALL §10; roadmap
  in-progress; manual-actions Open + inline SQL.

### Server-side state touched

- **Migration applied on prod 2026-05-17** (user-confirmed;
  `manual-actions.md` → Completed): `2026-05-17-term-prefs.sql`
  (`CREATE TABLE user_term_prefs`). `routes/feed.py` reads it every
  signed-in feed load (BUG-007 class if absent; anon unaffected). No
  cron/env/pip/symlink. Python App restart on deploy.

### Verification

`test_term_prefs.py` 17/17 + `test_ranking` green in-sandbox; changed
Python `py_compile` clean. Full suite needs flask/pymysql (documented
sandbox limit); route + browser UX deferred to CI. v1 = plain substring
match ("crypto" also hits "cryptography"); phrase/entity-aware is v2
(shared with topic extraction); `_MATCH_EXPR` is the single point to
later also match `article_bodies`.

### PR

- **PR #77** — Keyword / topic mute & boost (merged 2026-05-17;
  migration applied on prod same day).

---

## 2026-05-17 — BUG-020: firehose accumulates instead of churning (PR #72)

### Context

User: "firehose doesn't actually show everything." `/firehose` polled
`/stream` every 4s with `hx-swap="innerHTML"`, replacing the table
with only the newest ≤25 classified rows each tick (no "Load more";
the route's `since` cursor was never sent). Everything past the newest
25 was dropped on every poll. User chose **"make it accumulate"**
(keep classified-only; stop the churn).

### What shipped

- **`app/firehose_cursor.py`** (new, pure/Flask-free/DB-free, mirrors
  `app/trending.py`): `firehose_cursor_clause()` builds a **keyset
  `(classified_at, id)`** WHERE fragment. Timestamp-only skips rows —
  `classified_at` is second-granularity and `classify_pending` writes
  same-second bursts (the real data-loss mechanism). Malformed id →
  no-cursor (never 500s).
- **`app/routes/firehose.py`** `stream()`: drops the unused `since`;
  three modes (no cursor → newest page; `after_*` → strictly newer,
  prepend; `before_*` → strictly older, "Load more"). `ORDER BY
  f.classified_at DESC, a.id DESC`; `classified_at_iso` space-form for
  an unambiguous string→DATETIME compare.
- **`firehose.html`**: stable `<tbody>`; poll prepends
  (`afterbegin`, `limit=100`), "Load more" appends (`beforeend`);
  cursors read live from DOM. Reuses the existing `.load-more` class —
  **no `style.css` change** (avoids the in-flight profiles PR).
  `firehose_rows.html` emits `<tr>`s only.
- **`tests/test_firehose_cursor.py`** — 9 sandbox-run cases.

### Server-side state touched

None. No DB/cron/env/symlink/pip change. Python App restart on deploy.

### Verification

Helper 9/9 in-sandbox; templates Jinja-parse; changed Python
`py_compile` clean. Route/browser (prepend, Load-more, pause/resume)
deferred to a real env / CI (no Flask/PyMySQL/browser in sandbox).
Caveats in `bugs.md` BUG-020: >100 classifications inside one 4s tick
leaves a gap until "Load more" (not reachable at the real write rate);
a later-reclassified row can re-appear at top (a dup, not a loss).

### PR

- **PR #72** — BUG-020 firehose accumulation (draft).

---

## 2026-05-17 — Across-the-spectrum in-feed (PR #69)

Roadmap Pri 7 / LOE 3 (ui, algo). The "+N angles" pill (added with the
story dossier, PR #43) previously navigated to `/story/<id>`. It now
**expands inline** on the feed card to show a few sibling outlets'
coverage of the same deduped story, with a "Full dossier →" link for
the deep dive — the ambient everyday cousin of the dossier. Reuses
existing dossier infra (story_id clustering, visibility rules); no new
data, no DB migration, no LLM call.

### What shipped

- **`app/spectrum.py`** (new, pure/Flask-free, mirrors
  `discussion.py`/`trending.py`): `pick_spectrum_sample(members,
  exclude_id, limit=3)` — drops the card's own article, round-robins
  across left/center/right so the sample spans the spectrum even when
  one side dominates, one article per source, newest-first,
  deterministic. `lean_bucket` thresholds mirror `story.py` (commented).
- **`app/routes/story.py`**: extracted the canonical-guard +
  visibility-scoped member query into `_fetch_cluster()` (shared,
  behavior-identical to the old inline `view()` code); new
  `GET /story/<id>/peek` renders a partial via the shared fetch +
  `pick_spectrum_sample`.
- **`partials/spectrum_peek.html`** (new): compact sibling list (lean
  dot, source, title w/ click-tracking, short lead) + "Full dossier →"
  + framework-free "Hide" (`onclick` clears the container, matches the
  existing inline-onclick convention).
- **`partials/feed_cards.html`**: the pill is now progressively
  enhanced — keeps its `href` to the full dossier (no-JS / no-HTMX
  fallback = today's exact behavior) and adds `hx-get`/`hx-target`/
  `hx-swap` to load the peek into a per-card `#spectrum-<id>`
  container. GET = no CSRF needed.
- **`style.css`**: append-only `.spectrum-*` block (palette matches
  `.dossier-discussion`); `.spectrum-peek:empty { display:none }` so
  the container is invisible until expanded.
- **Tests**: `tests/test_spectrum.py` (new, 10 pure cases — run green
  in-sandbox) + 5 `tests/test_story.py` peek-route cases (404 guards,
  sibling render excludes the card article, partial has no base
  chrome).

### Code touched

- `news/app/spectrum.py` (new), `news/app/routes/story.py`,
  `news/app/templates/partials/spectrum_peek.html` (new),
  `news/app/templates/partials/feed_cards.html`,
  `news/app/static/style.css`,
  `news/tests/test_spectrum.py` (new), `news/tests/test_story.py`,
  `roadmap.md`.

### Server-side state touched

None. No DB migration, cron, env-var, symlink, or pip dep. Standard
Python App restart on deploy so the new `story.peek` route + templates
load. **No `manual-actions.md` entry.**

### Verification

- `test_spectrum.py` 10/10 pass in-sandbox; `app/spectrum.py` +
  `app/routes/story.py` `py_compile` clean; all touched templates
  Jinja-parse. Route/browser testing of `/story/<id>/peek` and the
  in-feed expansion is deferred to CI / a real env (sandbox has no
  Flask/pymysql/pytest — same documented limit as PR #50/#53/#59).

### PR / Open items

- **PR #69** — merged 2026-05-17. Rebased twice (behind PRs #56/#62/
  #64/#66, then #65/#67/#68/#71); `feed.py` deliberately untouched
  (zero overlap with the algo-profiles work, merged as PR #65),
  `style.css` append-only, `story.py` not in any other PR's scope.
- This wrap-up ran the archive procedure (4 oldest full entries →
  `engineering-history-archive.md` + Condensed history).
- Maintainer/CI: click a multi-source card's "+N angles", confirm the
  inline panel loads sibling angles + "Full dossier →", Hide clears
  it, and no-JS still navigates to `/story/<id>`.

---

## 2026-05-17 — Full-text article search (PR #70)

Roadmap "Search across articles" (Pri 6, LOE 6). v1 = MySQL InnoDB
FULLTEXT, no new dependency.

### What shipped

- **`app/routes/search.py`** (new blueprint, no url_prefix) —
  `GET /search?q=&page=`. Pure helpers `clean_query`
  (trim/collapse-ws/200-char cap) + `parse_page` (sandbox-testable
  like feed.py's `_normalize_sort`). Query bound as a parameter into
  `MATCH (a.title, a.summary) AGAINST (%(q)s)` (NATURAL LANGUAGE
  MODE — boolean operators are literal, no injection surface).
  Results deduped by story cluster and scoped by the exact
  source-visibility (`owner_id`) + per-user mute
  (`COALESCE(usp.weight,1.0)>0`) rules the feed uses; `ORDER BY
  relevance DESC, a.published_at DESC`; fetches `PAGE_SIZE+1` to
  drive Load-more without a COUNT.
- **Schema** — `FULLTEXT KEY ft_articles_search (title, summary)`
  in `seed/schema.sql` + migration
  `seed/migrations/2026-05-17-search-fulltext.sql`.
- **Templates** — `search.html` + `partials/search_results.html`
  (lighter card than feed_cards, reuses `.card` CSS, self-replacing
  HX Load-more, no `hx-select`); `base.html` nav gets a compact GET
  search box (value persisted via `request.args.get('q')`).
- **`app/static/style.css`** — appended `.nav-search` /
  `.search-page-form` block at EOF (no existing rule touched).
- **Tests/docs** — `tests/test_search.py` (pure helpers; same
  Flask-less sandbox limit as test_feed_sort.py, run on CI);
  INSTALL.txt §10 FULLTEXT limits.

### Server-side state touched

One **manual prod migration** (`manual-actions.md` Open, full
inline SQL): `ALTER TABLE articles ADD FULLTEXT INDEX
ft_articles_search (title, summary);`. `/search` 500s until applied;
all other routes unaffected. No cron/env/symlink/pip change.
Standard Python App restart on deploy.

### Verification

Helper assertions pass (stubbed import); `py_compile` +
Jinja-parse clean. Route SQL / in-browser UX deferred to CI / real
env (sandbox has no Flask/pymysql/pytest — documented limit, same
as PR #50/#59). Rebased onto `origin/main` twice as parallel PRs
landed (#56/#62/#64/#65, then #67/#68/#71 trending); conflicts
resolved in `__init__.py` (all blueprints), `style.css` /
`INSTALL.txt` (append both blocks), `manual-actions.md` (two Open
entries), `engineering-history.md` (took main's base, re-inserted
this entry).

### PR

- **PR #70** — Full-text article search (merged 2026-05-17). Branch
  `claude/onboard-news-aggregator-j0JdN`. FULLTEXT migration applied
  on prod 2026-05-17 (manual-actions.md Completed).

### Open items

- Merged + FULLTEXT migration applied on prod. Maintainer spot-check
  when convenient: `/search` via the nav box → results → Load more,
  confirm muted-source/visibility scoping in a real env.
- v2: search extracted `article_bodies` text; blended
  relevance×recency score; boolean/phrase mode.

---

## 2026-05-17 — Trending topics view (/trending page, PR #71)

Roadmap Pri 7 / LOE 5. New `/trending` page ranking topics by
**distinct-outlet count** ("20 outlets beat one outlet ×20"), each
linking to the dossier(s) under it. The roadmap's plan put topic
extraction in the `classify_pending` Haiku call; PR #56 was rewriting
that file, so the user chose (AskUserQuestion) the conflict-free route:
**reuse the Google Trends/News topic index `trending_poll` already
builds every 30 min** (PR #53) — no LLM, no `classify_pending` edit.

- `trending_poll` now also rebuilds `trending_topics` /
  `trending_topic_articles` in full each tick, in the same transaction
  as the existing `article_features.trending` scalar (unchanged).
- Pure helpers in `app/trending.py`: `topic_key` (sha1 of sorted
  tokens — collapses near-dup headlines), `topic_matches`
  (`score_article` refactored to its max, identical output, covered by
  the existing suite), `build_persist_rows`, `group_topic_stories`;
  `build_topic_index` tags `origin`. +14 `test_trending.py` cases.
- New blueprint + template + nav + additive CSS; env-defaulted
  `TRENDING_*`. Fragmentation handled by `topic_key` +
  `TRENDING_MIN_SOURCES` (default 2) floor (no clustering). Visibility
  mirrors feed/dossier. Limit (INSTALL §8K/§10): only surfaces topics
  also trending on Google — internal LLM-entity version is the
  follow-on (pairs with Signal Learning), deferred until PR #56 lands.

**Server state:** migration `CREATE TABLE trending_topics` +
`trending_topic_articles` **applied on prod 2026-05-17** (user-
confirmed; `manual-actions.md` → Completed; in `schema.sql` + a
migration file for fresh installs). **No new cron** — existing
`trending_poll` fills them next tick (folded into the durable Cron
list). No pip/env/symlink. Python App restart on deploy.

**Verification:** pure helpers verified in-sandbox (ad-hoc harness;
pytest/flask/pymysql unavailable — same limit as PR #50/53);
`score_article == max(topic_matches)` confirmed; templates Jinja-parse;
changed Python `py_compile`s clean. Live route/browser UX deferred to a
real env. **Open:** confirm `logs/cron.log` `topics_persisted=T
topic_matches=M` after a tick; LLM-entity follow-on once PR #56 lands.

---

## 2026-05-17 — Multiple saved algorithms / profiles

### Context

Roadmap "User-empowerment cluster" Theme A item (Pri 7, LOE 4). Until
now there was effectively one algorithm per user: every resolver
(`feed.py`, `firehose.py`, `jobs/send_digest.py`, `algo.py`) reads
`user_algorithms WHERE user_id=%s AND is_active=1 ORDER BY updated_at
DESC LIMIT 1`, and the `/algo` route only ever upserted that single
active row. The `user_algorithms` table **already** had `name` +
`is_active` columns (schema since v1), so this is a pure
application-layer change — **no DB migration, no manual prod action.**

### What shipped

- **`app/routes/algo.py`** — `_list_profiles`, `_set_active`
  (deactivate-all-then-activate-one, the single-active invariant the
  resolvers depend on), `_clean_name` (trim + 120-char cap to match
  the column + "Custom" fallback), `_return_redirect` (whitelisted
  feed/algo only — no open redirect). Four new login-required POST
  endpoints: `/algo/profiles/create` (save current editor sliders as
  a new named profile, made active — also the persistence path for
  the NL builder's proposed weights), `/profiles/activate`,
  `/profiles/rename`, `/profiles/delete`. Delete refuses the last
  profile (a zero-row user gets bounced into onboarding) and promotes
  a survivor if the active one is removed. Ownership enforced in SQL
  (`WHERE id=%s AND user_id=%s`) or an explicit owned-row check.
  `execute()` already returns `cur.lastrowid`, so create uses that
  directly (no `LAST_INSERT_ID()` round-trip).
- **`app/templates/algo.html`** — new "Profiles (N)" tab listing
  saved profiles with active badge + Use/Rename/Delete; a "Save as
  new profile" name field + native submit (`formaction`) inside
  `#algo-form` so all slider values post along with it (the form's
  explicit `hx-trigger` excludes `submit`, so htmx doesn't hijack it).
- **`app/routes/feed.py` + `feed.html`** — `_switcher_profiles`;
  feed-header `<select>` switcher (shown only with ≥2 profiles) posting
  to `algo.activate_profile` with `return_to=feed`.
- **`app/static/style.css`** — appended `.profile-*` / `.save-as` /
  `.profile-switch` block (no edits to existing rules; conflict-safe).
- **`tests/test_algo_profiles.py`** — 10 cases over an in-memory
  `user_algorithms` store (test_signals pattern): create activates &
  deactivates others, blank-name default, activate single-active +
  return_to, foreign-id no-op, rename, delete-when-multiple,
  delete-last refused, delete-active promotes survivor, login
  required. Runs on a real env; environmental ModuleNotFoundError in
  this sandbox (no flask) exactly like `test_signals`/`test_story`.
  Runnable suite unaffected: 113 pure-logic tests still pass.

### Existing behavior preserved

`save()` still edits the active row in place; `use_preset()` still
replaces the active row's name+weights; `onboarding()` still inserts
the first row active. None of these can produce >1 active row given
the new `_set_active` is the only multi-row creator.

### Server-side state touched

None. No DB migration (columns pre-existed), no cron, no env-var, no
new pip dep, no symlink. Standard Python App restart on deploy so the
new routes/templates load.

### PR

- **PR #65** — Multiple saved algorithms / profiles (draft).

---

## 2026-05-17 — Dark mode (PR #63)

Roadmap Pri 3 / LOE 2 (ui). Maintainer-picked. Client-only theme;
no server state, no DB, no manual prod action.

### What shipped

- **`style.css`** — `:root` gains semantic surface vars
  (`--surface`/`--surface-2`/`--surface-3`/`--notice-bg`/
  `--notice-border`/`--err-bg`/`--warn-bg`) with the *current* light
  values, so light mode is byte-for-byte unchanged. A new
  `:root[data-theme="dark"]` block overrides all palette vars (incl.
  brighter `--accent`/`--left`/`--right`/`--ok`/`--warn`/`--err` for
  legibility on dark). ~30 hardcoded literals (`background: white`,
  the `#f0efeb`/`#f7f6f0`/etc. fill family, `#333` lead, `#e3e3df`
  feature-bar track) repointed at the vars — without this the panels
  stayed white on a dark page. `color-scheme` per theme so native
  controls/scrollbars follow. `color: white` on accent buttons left
  literal (correct).
- **`base.html`** — synchronous head script (before the stylesheet
  link) sets `<html data-theme>` from `localStorage.theme`, falling
  back to `prefers-color-scheme` — no FOUC. A `linkbtn`-styled
  `#theme-toggle` button is the last nav item (signed-in or out);
  end-of-body script toggles the attribute, persists to
  `localStorage`, and relabels Dark/Light + `aria-pressed`. Pure
  client-side (no POST) so no CSRF/route/DB involvement.

### Code touched

- `news/app/static/style.css` — theme vars + literal→var repointing.
- `news/app/templates/base.html` — head theme-init, nav toggle,
  toggle wiring.
- `roadmap.md` — Dark mode → in-progress (→ Done on merge).

### Server-side state touched

None. CSS/template only; zero Python. Standard Python App restart on
deploy so the new template/CSS load (Jinja autoreloads templates;
restart is cleaner).

### Verification

- `base.html` Jinja-parses clean; no `.py` touched (suite unaffected;
  sandbox has no pytest/Flask — same documented env limit as PR #50).
- All hardcoded surface literals confirmed mapped (only `color:
  white` on accent + the `:root` var *definitions* remain by design).
- **Not verified**: in-browser toggle/persistence/no-FOUC and the
  dark palette's per-page contrast — deferred to a real env / CI
  (no Flask in sandbox).

### Open items

- Maintainer/CI: load `/`, `/algo`, `/firehose`, `/admin`, `/read`,
  `/story` in dark; toggle; hard-reload (confirm no light flash);
  cross-tab persistence. Tune any dark palette value that reads poorly.
- `engineering-history.md` is at its ~34 KB budget — archive oldest
  entries at the next wrap-up (deliberately not done here to keep this
  low-risk UI PR off the high-conflict archive path).

### PR

- **PR #63** — Dark mode (draft).

---

## 2026-05-17 — Article save / bookmark (roadmap Pri 6)

Roadmap "Article save / bookmark" (Pri 6, LOE 4, new-feature/ui).
Maintainer-picked. Reader view (PR #21 body extraction) is already
live, so the headline value — a **durable personal archive** — is
realizable now; article summaries (a soft pairing) are still backlog
and explicitly out of scope here.

### What shipped

- **Schema** — new `user_saves(user_id, article_id, folder DEFAULT
  'Read Later', saved_at, read_at)` (PK `(user_id, article_id)`, FKs
  cascade). Migration `seed/migrations/2026-05-17-user-saves.sql` +
  `schema.sql`.
- **`app/routes/saves.py`** (new blueprint, no url_prefix; mirrors the
  signals blueprint's INSERT/DELETE+JSON convention). `POST
  /save/<id>` toggles (returns `{saved: bool}`); `POST /save/<id>/read`
  sets `read_at` once (keepalive fetch on click-through); `GET /saved`
  (`login_required`) lists newest-first.
- **Durable archive** — `jobs/maintenance.py` now exempts saved
  articles from BOTH retention prunes (`articles` and
  `article_bodies`) via `NOT EXISTS (SELECT 1 FROM user_saves …)`, so
  a bookmark keeps its reader-view copy readable indefinitely. (The
  pre-existing maintenance comment anticipated exactly this.) Old
  saved articles don't pollute the feed — the feed query is windowed
  to `published_at >= now-7d`, so they only live on `/saved` + `/read`.
- **UI** — ☆/★ save button on every signed-in feed card, wired
  through the existing `cardSignals` Alpine component (new `saved`
  state + `toggleSave()`; `a.saved` batch-attached in `feed.py`
  exactly like `a.thumb`). New `/saved` page (scoped-style, Alpine
  per-row remove, "archived" vs "link only" badge keyed on
  `article_bodies.status`). "Saved" nav link in `base.html`.
  CSRF: ☆ uses `X-CSRF-Token` header (fetch); remove/mark-read same.
- **Tests** — `tests/test_saves.py` (11 cases: toggle/untoggle, auth
  401, folder passthrough/fallback, mark-read, anon redirect, list +
  empty state), same monkeypatch-DB pattern as `test_signals.py`.

### Server-side state touched

One DB migration (`user_saves`). **Load-bearing PRE-MERGE** (BUG-007
class): merged code reads `user_saves` on every signed-in feed load
and in `maintenance`. Logged in `manual-actions.md` → Open with full
inline SQL + pasted in chat; apply before merge, then Python App
restart. No new cron, env var, pip dep, or symlink.

### Verification

`py_compile` clean; all touched templates Jinja-parse. Flask
route/browser testing deferred to CI — sandbox has no Flask/pytest
(same documented limit as PRs #50/#56/#59). Logic reviewed.

### Parallel-session notes

Touches `feed.py`/`feed.html` (in-flight **PR #61** profiles),
`style.css` (PR #61 appends a different block), `base.html`,
`maintenance.py` (in-flight **PR #56** popularity/journalist —
different statements). All edits localized/append-style; rebased on
`origin/main` before opening the PR. Expect to rebase again behind
#61/#56 if they land first.

### PR

- **PR #64** — Article save / bookmark (merged 2026-05-17). Rebased
  twice (behind PR #56 classifier fixes, then PR #62 onboarding);
  `maintenance.py` / `style.css` / `engineering-history.md` conflicts
  resolved each time. Follow-up tracking-doc cleanup landed separately.

### Open items

- **Migration applied post-merge (2026-05-17).**
  `2026-05-17-user-saves.sql` was NOT confirmed applied before PR #64
  merged — signed-in `/` 500'd + nightly `maintenance` would have
  errored in the deploy→migration gap. User ran the `CREATE TABLE` +
  Python App restart same day; `manual-actions.md` → Completed.
  **Process learning (BUG-007 recurrence):** a load-bearing migration
  must gate the PR merge, not trail it — when `manual-actions.md` has
  an Open load-bearing entry tied to a PR, don't merge that PR until
  the user confirms the migration ran.
- v2 (roadmap): folder management UI, "N unread in Read Later" home
  prompt, keyboard `s` to save, export OPML/Markdown, extended
  retention pairing with summaries/TTS.
- Signal Learning (Pri 8): saves live in `user_saves`, not
  `user_signals` — that session should read from `user_saves` (or add
  a `save` signal then) rather than double-implement.

---

## 2026-05-17 — Onboarding interview / cold-start (PR #62)

### Context

Roadmap Pri 7 / LOE 4, Theme A of the user-empowerment cluster. A basic
`/algo/onboarding` already existed (a 4-preset radio picker). Upgraded it
into a real cold-start interview so a new reader's first feed isn't the
generic `balanced` preset.

### What shipped

- **`app/onboarding.py`** (new, Flask-free — mirrors `algo_nl.py` /
  `language.py`). Pure helpers: `normalize_categories` (intersect with
  the `CATEGORIES` catalog, dedupe, catalog order), `lean_direction`
  (5-point balance key → signed `political_lean` direction; unknown →
  center), `build_onboarding_weights` (copy the `balanced` preset, layer
  on `category_filter` + `political_lean_direction`; never mutates
  `PRESETS`), `top_trusted_sources` (dedupe candidate source rows by
  name keeping the best reputation, sort, cap).
- **`app/routes/algo.py`** — only the `onboarding()` route changed
  (PR #59's editor surface left untouched). Now idempotent: if the user
  already has an algorithm it redirects to the editor instead of
  stacking a second active row. GET renders the interview (topics,
  political balance, top-reputation trusted sources). POST builds the
  tailored weights, inserts one `user_algorithms` row ("My starting
  feed"), and boosts each picked source via `user_source_prefs`
  (weight 1.5, reusing the PR #19 feed multiplier). Source ids are
  validated against the global active pool before any write.
- **`app/routes/auth_routes.py`** — signup now redirects to
  `algo.onboarding` (was `algo.index`), so the interview is the actual
  first-run screen.
- **`onboarding.html`** rewritten (3 sections, carries `csrf_field()`
  per the now-merged CSRF PR #58); single appended
  `.onboarding-interview` CSS block + a mobile rule.
- **`tests/test_onboarding.py`** (new) — 10 pure-helper cases (verified
  green via direct import; sandbox has no pytest/Flask, same documented
  limit as PR #50/#58) + 4 route cases (create_app + stubbed
  query/execute, mirrors `test_signals.py`) for the maintainer's full
  Flask run.

### Server-side state touched

None. No DB migration (`user_algorithms` / `user_source_prefs` already
on prod; `category_filter` lives inside `weights_json`), no new cron, no
new dependency, no env var. Standard Python App restart on deploy so the
new route/template load — not a tracked manual action.

### PR

- **PR #62** — Onboarding interview / cold-start (merged 2026-05-17).

---

## 2026-05-17 — Classifier/feature review: fixed BUG-016..019

### Context

User asked for a review of the classifiers and features for bugs and
poor performance. Read the full classifier/feature/ranking surface
end-to-end. 11 findings (4 high, 4 medium, 3 low); user chose to fix
the four high-severity ones. M/L items deferred (listed under Open).

### What shipped (PR #56, merged 2026-05-17)

- **BUG-016 — popularity chronically under-counted.** First feature
  INSERT hard-wrote `popularity=0.0`; `popularity_poll` only UPDATEs
  existing rows, so anything trending while still `pending` lost its
  signal and nothing reconciled from `popularity_signals`. New shared
  `app.classifier.popularity_score()` (popularity_poll delegates to
  it); `classify_pending` seeds popularity from prior signals;
  `maintenance.py` nightly authoritative SQL reconciliation
  (`LN(1+score+2*comments)/LN(1+cap)`, 7-day window, idempotent) via
  shared `_POPULARITY_LN_DENOM` so Python & SQL agree.
- **BUG-017 — journalist_reputation penalized bylined articles.**
  `first_seen_at` defaulted to row-insert time → tenure≈0 → rep≈0.3,
  below the ~0.6 no-byline fallback. `_ensure_journalist()` seeds
  `first_seen_at` from `published_at`; `maintenance.py` floors rep at
  `GREATEST(avg_rep, 0.5*avg_rep+0.5*tenure)` (tenure clamped ≥0) so
  it's upside-only.
- **BUG-018 — `simhash==0` megacluster.** Empty/all-stopword articles
  got simhash 0 and clustered at Hamming-0 with every other zero,
  vanishing from the deduped feed behind a bogus canonical.
  `_assign_story_id` skips the simhash branch when `my_sim` falsy and
  excludes `a2.simhash=0`; `fetch_feeds` stores `NULL` for 0.
- **BUG-019 — LLM-fallback contamination permanent + unmarked.**
  `_classifier_version()` tags fallback rows `<ver>-nollm`; bounded
  `_reclassify_nollm()` re-runs the LLM over oldest tagged rows (one
  `LLM_BATCH_SIZE`/tick) when the pending queue is drained and budget
  remains, restoring the clean version. Persistent outage just leaves
  rows tagged. Per-tick log line gains `reclassified=N`.

### Code touched

- `app/classifier/rules.py` (popularity_score + `_POPULARITY_*`),
  `app/classifier/__init__.py` (export), `jobs/popularity_poll.py`
  (delegate; drop unused `import math`), `jobs/classify_pending.py`
  (popularity seed, `_classifier_version`, `_ensure_journalist`
  first_seen, simhash-0 guard, `_reclassify_nollm`),
  `jobs/fetch_feeds.py` (NULL for 0 simhash), `jobs/maintenance.py`
  (popularity reconcile + journalist rep floor).
- Tests: `test_rules.py` (+popularity_score & cron parity),
  `test_assign_story_id.py` (+simhash-0; `FakeCursor` gained a
  parallel `sql_log`, 2-tuple `calls` contract unchanged),
  `test_classify_pending.py` (new, +18 cases). Full suite **245
  passing** after rebase onto `origin/main` (PR #50/52/53/54/55).

### Server-side state touched

**None.** No DB migration / schema / cron / env / pip / symlink
change — code-only in cron scripts + a pure helper. Cron picks up new
code on the next tick; no web route changed (no Python App restart
strictly required). **No `manual-actions.md` entry.** Next-session
notes: rows written `classifier_version='v1'` during a *past* LLM
outage are not retroactively detectable (only rows tagged going
forward self-heal); existing `popularity=0.0` rows self-heal on the
next nightly `maintenance`; pre-existing `simhash=0` rows are now
ignored by clustering and age out.

### PRs

- **PR #56** — Classifier/feature review fixes (BUG-016..019). Merged
  2026-05-17.

### Open items (remaining review findings, not yet actioned)

- M5: `story_obscurity` counts only exact `title_hash` dupes, not the
  simhash cluster (wrong for re-headlined syndication; weight 0 latent).
- M6: no general rescore path beyond the `-nollm` heal.
- M7: `_assign_story_id` window keyed to NOW → dedup degrades during/
  after a classify backlog.
- M8: LLM partial responses fail silent; `max_tokens=2048` is an
  unguarded cliff if `LLM_BATCH_SIZE` is raised.
- L9: `info_density`/`reading_level` use the RSS blurb, not the
  extracted body; `_CAP_TOKEN` over-counts Title-Case headlines.
- L10: `popularity_poll._normalize_url` `lstrip("www.")` strips a char
  set, not the prefix — latent, harmless only because symmetric.
- L11: `country`/`region` written but unused in ranking/filters
  (spec feature #9 "geography" effectively unimplemented).
- Perf: simhash candidate query is an unindexable `BIT_COUNT` scan
  over 48h/pending row — fine now, watch as the catalog grows.

---

## 2026-05-17 — CSRF protection + auth rate limiting (PR #58)

Roadmap Pri 7 / LOE 4 (security). v1 was same-site-cookie only —
every POST forgeable. User chose **hand-rolled zero-dep CSRF** +
**in-memory rate limit** (avoids another cPanel `pip install`, a
`requirements.txt` conflict with parallel work, and any manual prod
action).

### What shipped

- **`app/security.py`** (new) — signed double-submit-cookie CSRF.
  Token `nonce.HMAC-SHA256(SECRET_KEY,nonce)` (stdlib only). Pure
  helpers (`make_csrf_token`/`csrf_token_valid`/`tokens_match`,
  no Flask import — testable like `app/language.py`). `init_csrf`
  registers: `before_request` resolving the `news_csrf` cookie
  (mints if missing/invalid) and rejecting unsafe-method requests
  400 unless `_csrf` form field **or** `X-CSRF-Token` header
  matches; `after_request` setting the cookie (httponly, Lax,
  Secure when `request.is_secure`, 30-day) only when freshly
  minted; context processor exposing `csrf_token` +
  `csrf_field()` (`markupsafe.Markup`, not removed `flask.Markup`).
  Registered before `_load_user` so forgeries die before the
  session lookup. Only exempt endpoint: `account.unsubscribe`
  (RFC 8058 one-click POST is tokenless + URL-token authenticated).
- **`app/ratelimit.py`** (new) — thread-safe `SlidingWindowLimiter`
  + `client_ip()` (XFF first hop → remote_addr). Limiter on
  `app.extensions` per `create_app()`. `/auth/login` + `/auth/
  signup` POST → 429 over limit. Default 10 / 300 s, env-tunable.
- **`CSRF_ENABLED`** config (default on). Mirrors Flask-WTF's
  test convention: `conftest.py` sets it `0` suite-wide (keeps the
  existing `test_signals.py` POSTs green untouched);
  `test_csrf.py` re-enables on its own app.
- **Templates** — `{{ csrf_field() }}` in all POST `<form>`s
  (incl. the PR #59 NL-builder `algo.describe` form picked up on
  rebase); `base.html` `<meta csrf-token>` + end-of-body script
  (`window.csrfToken` + `htmx:configRequest` header hook covering
  algo `hx-post` preview/save); `X-CSRF-Token` header added to the
  5 plain `fetch()` POST sites (signals + click tracking).
- **Tests** — `test_ratelimit.py` (pure, run in-sandbox) +
  `test_csrf.py` (pure helpers + Flask-integration). Pure logic
  verified locally; Flask cases run on CI (sandbox has no
  Flask/pytest — same env limit as PR #50).
- **Docs** — INSTALL.txt §2b (optional `CSRF_ENABLED`/
  `AUTH_RATELIMIT_*` + SECRET_KEY-must-be-real) and §10
  (CSRF + rate limit shipped; per-worker caveat).

### Server-side state touched

None — no DB/cron/symlink/pip change. New env vars have working
defaults. **Standard Python App restart on deploy** (Passenger
import cache). CSRF HMAC uses the existing real `SECRET_KEY` cPanel
env var — no action needed.

### Notes for next session

- Rate-limit counters are per Passenger worker; DB-backed
  cross-worker upgrade noted in INSTALL §10 (only if distributed
  credential-stuffing shows up).
- CSRF cookie refreshes only when missing/invalid (stable across
  tabs); helper supports per-form rotation if ever needed.
- Email verification on signup (Pri 5) pairs with this + digest
  SMTP.

### PR

- **PR #58** — CSRF protection + auth rate limiting (draft).

---

## 2026-05-17 — Natural-language algorithm builder (+ user-empowerment roadmap cluster)

### Context

Session opened as a brainstorm: "more features for the roadmap —
empower the user to help build the perfect newsfeed." Added a 10-item
cluster (themes A/B/C: direct algorithm expressiveness, closing the
feedback loop, crowdsourcing the feed), then implemented the flagship
A item.

### What shipped

- **Roadmap cluster** — 10 backlog entries (NL builder, keyword
  mute/boost, multiple saved algos, A/B split feed, onboarding
  cold-start, tune-from-article, feed check-in, shareable algo
  gallery, community source-quality overlay, community add-a-source).
  "Tune from this article" cross-references the Signal Learning item
  so it isn't double-implemented.
- **Natural-language algorithm builder** (roadmap Pri 8, LOE 5). User
  describes the feed they want in plain English; one Haiku call maps
  it onto the existing 3-axis `FEATURES` catalog and the `/algo`
  editor is pre-filled for review. Nothing is saved until the user
  hits Save (reuses the existing `/save` path — no new persistence,
  **no DB migration**). Any LLM failure (no key, parse error, API
  error, all-zero output) falls back to the editor unchanged with an
  inline note — never 500s, no per-request LLM cost (fires only on
  explicit submit).

### Design notes

- `app/algo_nl.py` is Flask-free and mirrors the
  `classifier/framing.py` convention (lazy `anthropic` import,
  `LLMUnavailable` on any failure, `_estimate_cost` reuse). The
  system prompt's feature catalog is generated from `ranking.FEATURES`
  at call time so it can never drift from the catalog.
- `_normalize()` clamps every value into range (weight [0,2],
  direction to the feature's signed/unsigned range, threshold to
  [0, scale] or None, recency [0,2]), drops unknown feature keys and
  unknown categories, and raises `LLMUnavailable` if the model
  produced no usable weights. Output is the exact on-disk weights
  shape, so `resolved_weights_for_view` / `weights_to_expression` /
  `build_score_sql` consume it directly.
- Editor entry point is a `method=post` form (full re-render of
  `algo.html`), not HTMX — the whole slider grid changes, so a plain
  POST is simpler and more robust than swapping the grid partial.

### Code touched

- `news/app/algo_nl.py` — new, pure helper + `interpret_algorithm`.
- `news/app/routes/algo.py` — `POST /describe`; shared
  `_render_editor()`; imports `interpret_algorithm` + `LLMUnavailable`.
- `news/app/templates/algo.html` — "Describe your ideal feed" panel
  on the UI tab; notes/error banners; echoes the description back.
- `news/app/static/style.css` — `.nl-builder` rule block.
- `news/tests/test_algo_nl.py` — new, 14 cases (anthropic stubbed via
  `sys.modules`, same pattern as `test_framing.py`).
- `roadmap.md` — user-empowerment cluster; NL builder `in-progress`.

### Server-side state touched

None. No DB migration, no cron entry, no env-var, no symlink, no new
pip dependency (reuses the `anthropic` SDK + `ANTHROPIC_API_KEY`
already used by classify/framing). Standard Python App restart on
deploy so the new route + template load.

### Verification

- `tests/test_algo_nl.py` 14/14 pass; full runnable suite **179
  passed** post-rebase. The 4 collection errors
  (test_discussion/feed_sort/signals/story) are the known sandbox
  `pymysql`→`cryptography` limit, unrelated to this change.
- `algo.html` Jinja-parses; changed Python files `py_compile` clean.
- **Not verified**: the live Flask `/describe` route and the in-browser
  UX — `app.db` (pymysql) can't import in this sandbox, so route- and
  browser-level testing is deferred to a real env / CI. Logic is
  covered by the pure-helper unit tests.

### PR

- **PR #59** — Natural-language algorithm builder + roadmap cluster
  (merged 2026-05-17). Rebased on `origin/main` after PRs #50–#55
  (langdetect → py3langid, discussion links, history archive) landed;
  roadmap.md + style.css auto-merged cleanly. Tracking-doc cleanup
  (roadmap → Done, this PR line) landed in a follow-up PR.

### Open items

- Maintainer/CI: run `pytest` in an env with flask+pymysql to exercise
  the `/describe` route, and click through `/algo` → "Build from
  description" → review sliders → Save.
- Possible polish: surface the model's per-feature rationale inline
  next to each slider (currently a single summary line). Out of scope
  this session.

---

## 2026-05-17 — BUG-015: external trending sort (Google Trends + Google News)

### Context

User reported that the Popularity sort (added PR #48) returned an
almost-all-Hacker-News feed. Logged as BUG-015. The sort was
`ORDER BY f.popularity DESC`, and `article_features.popularity` is
written only by `popularity_poll` from Reddit/HN *URL* matches (~5-10%
match rate, HN-skewed), so it degenerated into "links that hit HN" and
dropped the user's algorithm entirely. User wants an *external* broad
trending signal (à la Google News) that re-ranks toward trending topics
*without* abandoning algo relevance — "choose the best articles that
match the popular topics". Chosen via AskUserQuestion: Google
News + Trends RSS as the source; rename the sort to "Trending" composed
with the algo.

### What shipped

- **`app/trending.py`** (new, pure/Flask-free, mirrors
  `app.discovery`/`app.language`). Parses Google Trends daily-trends
  RSS (`parse_trends_rss`, reads `<ht:approx_traffic>` when present)
  and Google News RSS (`parse_gnews_rss`, strips the trailing
  " - Publisher"). `build_topic_index` reduces both to weighted topics
  (token bag + 0..1 heat: traffic-log or positional rank; Trends
  weighted 1.0, GNews 0.8). `score_article` = max over topics of
  (fraction of the topic's tokens present in title+summary lead) ×
  topic heat, clamped 0..1. No URL matching — Google News RSS links
  are opaque redirects; topic/keyword overlap is the honest signal.
  No new pip dependency (lazy `feedparser`, already stubbed in tests).
- **`jobs/trending_poll.py`** (new cron, every 30 min). `job_lock`,
  bounded HTTP (~6 small GETs, `TRENDING_BUDGET_SECONDS=60`),
  `conn.ping(reconnect=True)` after the RSS fan-out before writes
  (BUG-009 lesson). Recomputes `article_features.trending` for the
  whole rolling `TRENDING_WINDOW_DAYS` (default 2) window every tick
  via `executemany`, so yesterday's hot topics decay to 0 on their own
  — no separate reset job.
- **Schema**: `article_features.trending FLOAT NOT NULL DEFAULT 0`
  (migration `seed/migrations/2026-05-17-trending.sql`). New `trending`
  entry in `app/ranking.py` FEATURES + `seed/feature_catalog.sql`,
  opt-in (`default_weight 0`) so existing user algorithms are
  unchanged and `build_score_sql` skips it until a user opts in.
- **`app/routes/feed.py`**: `SORT_OPTIONS` `popularity` → `trending`
  (label "Trending"); `_SORT_ALIASES` maps legacy `popularity` →
  `trending` so old bookmarks / threaded category links / digest URLs
  don't silently fall back to relevance; `_order_by_for_sort` for
  trending is `ORDER BY f.trending DESC, score DESC` (trending heat
  first, user algo score as the within-trending tiebreak). `f.trending`
  added to the SELECT. Templates need no change — they iterate
  `sort_options`/`sort_labels`.
- **Tests**: `tests/test_trending.py` (new, 18 cases — tokenize,
  RSS parse w/ stubbed feedparser, topic-index heat, scoring incl.
  partial/zero/clamped/summary-fallback). `tests/test_feed_sort.py`
  updated for the rename + legacy alias + new ORDER BY.
  `test_trending` + `test_ranking` = 45 passing locally; full suite
  unrunnable in the sandbox (no Flask/pymysql — same documented
  environmental limitation as PR #50), feed.py logic validated via
  a stubbed-import harness.

### Code touched

- `news/app/trending.py` — new pure helpers.
- `news/jobs/trending_poll.py` — new cron.
- `news/app/ranking.py` — `trending` FEATURES entry.
- `news/app/routes/feed.py` — sort rename + alias + ORDER BY + SELECT.
- `news/seed/schema.sql`, `news/seed/feature_catalog.sql`,
  `news/seed/migrations/2026-05-17-trending.sql`.
- `news/tests/test_trending.py` (new), `news/tests/test_feed_sort.py`.
- `news/INSTALL.txt` — cron line §4c, troubleshooting §8J, §10 limit.
- `bugs.md`, `roadmap.md`, `manual-actions.md`.
### Server-side state touched

- **Migration pending on prod**:
  `seed/migrations/2026-05-17-trending.sql` (one `ALTER TABLE
  article_features ADD COLUMN trending`). The Trending sort and the
  `trending_poll` job error until the column exists. Tracked in
  `manual-actions.md` Open with full inline SQL; the other sorts
  (relevance/newest) are unaffected, but the Trending sort itself 500s
  on the missing column until applied — apply before merge.
- **New cron entry pending**: `trending_poll.py` every 30 min. Inert
  (writes nothing meaningful) until the migration is applied; wrapped
  in `job_lock` so it no-ops safely on overlap.
- No new pip dependency, no new env var required (all `TRENDING_*`
  have working defaults), no new symlink. Python App restart after the
  migration so the renamed sort + new column load.

### Open items

- Watch the first few `trending_poll` ticks in `cron.log`:
  `topics=T gnews=G articles=N matched=M`. `matched` in the low
  hundreds is expected; if `topics=0`, Google may be rate-limiting the
  RSS — non-fatal (job writes trending=0, feed falls back to algo).
- Token-overlap matching misses entity synonyms ("Fed" vs "federal
  reserve"). The principled upgrade is entity extraction shared with
  the roadmapped Trending-topics-view / Signal-Learning work.

### PR

- **PR #53** — BUG-015: external trending sort (merged 2026-05-17;
  DB migration + trending cron applied on prod same day).

---

## 2026-05-17 — Techmeme-style discussion links (Reddit/HN)

### Context

User asked for "a feature like what Techmeme does where they list
relevant tweets regarding the article/topic" — i.e. Techmeme's
"Discussion:" line. Literal X/Twitter needs the paid API (~$100/mo,
already flagged on the roadmap social-firehose item); the user picked
**Reddit + HN only** for v1 and **feed card + story dossier** as the
surfaces. This is mostly wiring up data we already fetch:
`popularity_poll` matches Reddit/HN threads to our articles every
30 min for the popularity score but previously discarded the thread
permalink.

### What shipped

- **Schema** — `popularity_signals` gains `permalink VARCHAR(1024)`
  and `subreddit VARCHAR(64)` (NULL for HN). Migration
  `seed/migrations/2026-05-17-discussion-links.sql`. Existing rows get
  NULL permalink and simply render no discussion line until
  `popularity_poll` refreshes them on its next tick.
- **`jobs/popularity_poll.py`** — Reddit posts now capture the full
  thread permalink (`https://www.reddit.com` + `data.permalink`) and
  `data.subreddit`; HN posts capture
  `https://news.ycombinator.com/item?id=<id>`. INSERT/ON DUPLICATE KEY
  UPDATE extended with the two new columns. No behavior change to the
  popularity score itself.
- **`app/discussion.py`** (new) — pure `discussion_label(source,
  subreddit)` ("Hacker News" / "r/<sub>" / "Reddit") plus
  `discussions_for_articles(ids)` (per-article map, comments desc) and
  `discussions_for_story(ids)` (one merged list across a cluster's
  members, deduped by thread URL keeping max comment count). Mirrors
  the Flask-free-helper convention of `discovery.py` / `feed_validation.py`.
- **`app/routes/feed.py`** — after the existing thumb attach, one
  batched `discussions_for_articles` call over the page's article ids;
  `a["discussions"]` rides into both the full and HX "Load more"
  renders.
- **`app/routes/story.py`** — `discussions_for_story` over the cluster
  members, passed to the dossier template.
- **Templates** — `feed_cards.html` gets a compact
  `Discussion: Hacker News (142) · r/technology (89)` line under the
  byline; `story.html` gets a `.dossier-discussion` panel above the
  lean columns. `style.css` gains additive `.discussion` /
  `.dossier-discussion` rules (muted, matches the framing panel
  palette).
- **Tests** — `tests/test_discussion.py` (11 cases): label variants,
  empty-input short-circuits the query, grouping + comments-desc sort,
  missing-id absent, `_merge` dedupe-by-url-keep-max + sort, story
  merge across cluster. `tests/test_story.py` `store` fixture also
  stubs `app.discussion.query` (the route now does one extra DB read).
  Full runnable suite: 177 passing (4 files need
  trafilatura/anthropic/lxml and are environmental, same sandbox
  limit noted on PR #50).

### Code touched

- `news/seed/schema.sql` — two columns on `popularity_signals`.
- `news/seed/migrations/2026-05-17-discussion-links.sql` — new.
- `news/jobs/popularity_poll.py` — capture permalink + subreddit.
- `news/app/discussion.py` — new helper module.
- `news/app/routes/feed.py`, `news/app/routes/story.py` — attach
  discussions.
- `news/app/templates/partials/feed_cards.html`,
  `news/app/templates/story.html`,
  `news/app/static/style.css` — UI.
- `news/tests/test_discussion.py` (new),
  `news/tests/test_story.py` (fixture stub).
- `roadmap.md`, `manual-actions.md` — new entries.

### Server-side state touched

- **Migration applied on prod (2026-05-17)**:
  `seed/migrations/2026-05-17-discussion-links.sql` —
  `popularity_signals` gained nullable `permalink` + `subreddit`.
  User confirmed the ALTER was run and the Python App restarted;
  entry moved to `manual-actions.md` → Completed. Both columns are
  nullable and only `popularity_poll` writes them, so it is not
  load-bearing beyond "the ALTER must precede the deployed code"
  (which it did). In the repo via `schema.sql` + the migration file,
  so fresh installs replay it.
- No new cron, env var, dependency, or symlink. Python App restarted
  post-deploy so the new blueprint code + templates loaded.

### PR

- **PR #52** — Techmeme-style discussion links (merged 2026-05-17).

### Open items

- After a couple of `popularity_poll` ticks, confirm on prod that
  discussion lines appear on cards whose URLs hit Reddit/HN (match
  rate is the usual ~5-10%, so most cards won't have one — that's
  expected, same as the popularity score).
- Natural follow-ons if the user wants more coverage: free Bluesky
  `searchPosts` harvest (no key, no new dep) feeding the same
  surface; paid X/Twitter is still gated on spend.

---

## 2026-05-17 — Engineering-history archive process

### Context

`engineering-history.md` had grown to ~34.8K tokens (~85 KB) — past the
25K single-`Read` ceiling — so the onboarding step "read it end-to-end"
could no longer be done in one pass. Introduced a token budget + an
on-demand archive so the working history stays ingestible without losing
historical detail.

### What shipped

- **`engineering-history-archive.md`** (new) — verbatim historical
  record, newest-first, same heading format. Read on demand
  (grep by PR#/BUG-ID/date) when troubleshooting or needing deep
  context; not part of normal onboarding.
- **`engineering-history.md` condensed** from ~85 KB (~34.8K tokens) to
  ~26 KB (~11K tokens).
  Kept the 3 most recent entries in full; everything from the 2026-05-13
  Story dossier (PR #43) back through the 2026-05-12 v1 deploy was moved
  verbatim to the archive and replaced with terse summaries (date,
  title, PR#, what shipped, load-bearing server-state one-liners).
- **New durable "Load-bearing production state" section** at the top,
  consolidating the not-in-repo server state (symlinks,
  `passenger_wsgi` backup, `.htaccess`, DB snapshot, cPanel env vars,
  hard rules, cron) out of the 2026-05-12 v1-deploy entry so it can
  never age out via condensation. "Original product spec" also stays in
  the live file.
- **Process documented** in `engineering-session-wrapup.md` (new
  Step 1b: check size at wrap-up, archive when over ~14K tokens /
  ~34 KB) and cross-referenced in
  `new-engineering-session-instructions.md` (Step 1 + tl;dr) so future
  sessions maintain it.

### Code touched

- `engineering-history.md` — split + condensed; durable Load-bearing
  section added.
- `engineering-history-archive.md` — new.
- `engineering-session-wrapup.md` — new "Archive
  `engineering-history.md`" step + anti-pattern.
- `new-engineering-session-instructions.md` — Step 1 + tl;dr updated for
  the live/archive split.

### Server-side state touched

None. Docs-only — no DB, cron, symlink, env-var, or pip change.

### PRs

- **PR #51** — Engineering-history archive process (merged 2026-05-17).

---

## 2026-05-17 — BUG-013 + BUG-014: Latin-script filter via py3langid

### Context

User reported still seeing non-English articles in the feed —
specifically German, Spanish, and Finnish (the hs.fi report was a
Finnish sports headline), all *fresh* (last day or two). The
English-only filter from PR #42 (`app/language.py`) was working as
designed; this is the limitation it explicitly documented: stages 1
(feed `<language>` tag) and 2 (non-Latin script ratio) cannot tell
English from German/Spanish/Finnish — they all use Latin letters, so
`_non_latin_letter_ratio` ≈ 0 and the article passes. The feeds in
question don't self-declare a non-English tag, so stage 1 misses them
too.

The first cut shipped `langdetect==1.0.9` (user's chosen approach over
a zero-dep heuristic or a per-source language column). That triggered
**BUG-014**: langdetect 1.0.9 is sdist-only and its old setup.py
fails to build under modern PEP 517/setuptools — `pip install` errors
with `Failed building wheel for langdetect`, so the package never
installs (reproduced locally and on the user's cPanel venv). User
chose to swap to **py3langid**, which ships a prebuilt wheel.

### What shipped

- **`app/language.py`** — added **stage 3** to `is_english`: when text
  survives stages 1+2 and has at least `MIN_DETECT_LETTERS=24` Latin
  letters, run the detector and reject only on a *confident*
  non-English call where English is an unlikely alternative
  (`top_prob >= 0.85` AND `english_prob < 0.10`). Deliberately biased
  toward keeping English — dropping a real English article is a more
  visible regression than an occasional foreign one slipping through.
  `_detect_lang_probs` builds a cached `py3langid` `LanguageIdentifier`
  (`norm_probs=True`) and reads `rank()`; py3langid is deterministic
  so no seeding. Lazy-imported inside a broad `except`: any failure /
  degenerate input / absent package → None → permissive accept, so
  the fetch loop never breaks.
- **`requirements.txt`** — `py3langid==0.3.0` (pulls `numpy>=2.0.0`,
  also wheel-distributed). Replaced the broken `langdetect==1.0.9`.
- **`tests/test_language.py`** — detector stubbed via `sys.modules`
  (fake `py3langid.langid`, same pattern as the trafilatura/anthropic
  stubs) so the suite is deterministic and passes without the package.
  21 → 30 cases: German/Spanish/Finnish rejection, English still
  accepted, short-text skips detector, low-confidence keeps,
  English-plausible keeps, detector-raises and detector-unavailable
  both fall through to accept. Also verified end-to-end against the
  real py3langid.
- **`news/INSTALL.txt` §10** — rewrote the English-filter limitation
  note to describe the three-stage filter, the conservative stage-3
  behavior, and the langdetect→py3langid rationale.

### Why py3langid

User picked langdetect for robustness over a zero-dep word-profile
heuristic; BUG-014 then proved langdetect operationally broken on the
target env (no wheel, fragile setup.py — the recurring install-pain
class this project keeps hitting). py3langid is a maintained
wheel-distributed langid fork: no build step (so BUG-014's failure
class cannot recur), deterministic, normalized 0..1 probabilities via
`rank()`, accurate on the reported samples incl. short headlines.
Still a manual pip-install prod action, but one that actually
installs; and the import fails soft so it is **not** a site-down risk.

### Code touched

- `news/app/language.py` — stage-3 py3langid detection + helpers
  (`_latin_letter_count`, `_detect_lang_probs`), tuning constants
  (`DETECT_MIN_CONFIDENCE`, `DETECT_ENGLISH_FLOOR`).
- `news/requirements.txt` — `py3langid==0.3.0` (was the
  briefly-shipped `langdetect==1.0.9`).
- `news/tests/test_language.py` — sys.modules stub fixture + 9 new
  cases (30 total).
- `news/INSTALL.txt` §10 — updated limitation note.
- `bugs.md` — BUG-013 logged + resolved; BUG-014 logged + resolved.
- `manual-actions.md` — Open entry for the pip install (py3langid).

### Server-side state touched

- **Manual prod action completed (2026-05-17)**: `pip install -r
  requirements.txt` run on cPanel (Terminal, venv activated — the "Run
  Pip Install" button is greyed out), installing `py3langid==0.3.0` +
  wheel-distributed `numpy`. Tracked in `manual-actions.md` (now
  Completed). The filter is live: `fetch_feeds` is a fresh per-tick
  cron process so it picks up py3langid on its next tick regardless of
  a Passenger restart (web routes don't use the detector). Was **not**
  a site-down risk while pending: the detector import is lazy and fails
  soft. py3langid + numpy are both wheel-distributed so the install was
  a plain download (no build step — this is what fixes BUG-014). No DB
  migration, no cron change, no env var, no symlink.
- The filter is fetch-time only — it does not purge non-English rows
  already in `articles`; those age out of the 7-day window
  (multiplicative recency gate from BUG-011 crushes them well before
  that).

### Tests

`tests/test_language.py` 30/30 pass (stubbed) and verified end-to-end
against the real py3langid (German/Spanish/Finnish rejected; English
incl. short + accented kept). Full local suite: 141 passed of the
runnable set (the sandbox can't build `cryptography`/`requests`/
`dotenv` so 5 collection-erroring + 13 missing-module test files are
environmental, unrelated to this change — confirmed all
`ModuleNotFoundError`).

### PR

- **PR #50** — BUG-013 + BUG-014: py3langid stage-3 for Latin-script
  European filtering (merged 2026-05-17; prod pip install applied
  same day).

---

## 2026-05-14 — Feed sort selector (Relevance / Newest / Popularity)

### Context

User asked for "the same sorts that Google has" on the feed. Google
News parity = a small dropdown with Relevance (algorithmic, default)
and Date. Added Popularity as a third option per the user's
selection — raw `article_features.popularity` (Reddit/HN signal),
useful for an "everyone's reading this" view that ignores the
user's algorithm tuning.

### What shipped

- **`app/routes/feed.py`** — new module constants `SORT_OPTIONS =
  ("relevance", "newest", "popularity")` and `SORT_LABELS`. Two pure
  helpers: `_normalize_sort(value)` (case-insensitive, trims, falls
  back to `relevance` on anything else — including SQL-injection
  attempts) and `_order_by_for_sort(sort)` returning the literal
  ORDER BY clause to inject. Route reads `request.args.get("sort")`,
  normalizes, and substitutes `{order_by_sql}` into the SQL template
  in place of the previous fixed `ORDER BY score DESC,
  a.published_at DESC`. Threshold filters, source-pref weights, and
  visibility filters all still apply — only the ordering changes.
- **`app/templates/feed.html`** — wrapped category tabs in a new
  `.feed-controls` flex row alongside a small `<form method="get">`
  with a `<select name="sort">` that auto-submits on change. Category
  tab `href`s thread `sort=` through `url_for` (omitting it when
  it's `relevance`, so the default URL stays clean: `/`,
  `/?category=tech`, `/?sort=newest`,
  `/?sort=newest&category=tech`).
- **`app/templates/partials/feed_cards.html`** — HTMX "Load more"
  button preserves `sort` the same way.
- **`app/static/style.css`** — single `.feed-controls` /
  `.sort-form` rule block; mobile media block stacks the form below
  the tabs at ≤640px.
- **`tests/test_feed_sort.py`** — 8 cases covering: SORT_OPTIONS
  shape; `_normalize_sort` passes through valid values; falls back
  to `relevance` for None/empty/whitespace/unknown/SQL-injection
  strings; case-insensitive + trim; ORDER BY for each sort puts the
  right column first; popularity ties break on recency (not score);
  unknown value defaults to relevance. Full suite: 190 passing (was
  182).
- Manual render smoke-test via test client: `/`, `/?sort=newest`,
  `/?sort=popularity`, `/?sort=bogus`, `/?sort=newest&category=tech`
  all return 200 with the correct option pre-selected.

### Notes for next session

- Behavior on `newest`: `recency` from the algorithm slider has no
  practical effect on the ORDER BY (we sort by `published_at`
  directly), but it's still computed in the score expression because
  `score DESC` is the tiebreaker. Filter thresholds still apply, so
  a paywall-hating user sorting by newest still won't see paywalled
  articles. That's correct: sort is a re-order, not an opt-out.
- `popularity` ties break on `published_at`, not on score.
  Acceptable — popularity sort is a deliberately algorithm-agnostic
  view.
- Firehose intentionally untouched — it already orders by
  `f.classified_at DESC` and is the see-everything stream.
- `FEED_JITTER` still applies to the score expression, so the page-1
  reload shuffle from BUG-012 keeps working under `relevance`.
  Jitter is wasted CPU on `newest` / `popularity` sorts since
  `score` is only a tiebreaker there; not worth conditionally
  skipping at this scope.
- Possible future polish: persist the last choice per-user (would
  need a `users.feed_sort` column) — explicitly out of scope per
  the user's "URL query param only" choice this session.

### Code touched

- `news/app/routes/feed.py` — sort helpers + route plumbing.
- `news/app/templates/feed.html` — `.feed-controls` row with
  category tabs + sort `<form>`; tabs preserve `sort=`.
- `news/app/templates/partials/feed_cards.html` — Load more button
  preserves `sort=`.
- `news/app/static/style.css` — `.feed-controls` / `.sort-form`
  rules + mobile media block stack.
- `news/tests/test_feed_sort.py` — new, 8 cases.
- `roadmap.md` — new Done entry; at-a-glance row added.

### Server-side state touched

None. No DB migration, no new cron entry, no env-var change, no new
symlink, no new pip dep. Standard Python App restart on deploy so
the new template + route load.

### PR

- **PR #48** — Feed sort selector (merged 2026-05-14).

---

## 2026-05-13 — BUG-012: refresh-shuffle via score jitter

### Context

User reported: "When someone refreshes their page, the content
presented should change as well." With BUG-011's multiplicative
recency gate the feed is fresh in absolute terms, but ranking is
purely arithmetic — `ORDER BY score DESC, a.published_at DESC` over
a deterministic score gives the same top-30 on every reload until
new articles land or recency decay reshuffles. Logged as BUG-012.

### Root cause

`app/ranking.py:build_score_sql` returns a pure SQL arithmetic
expression with no random component. Identical inputs → identical
outputs. Refresh feels static.

### Fix

Opt-in `jitter` kwarg on `build_score_sql(weights, *, jitter=0.0)`.
When `jitter > 0` AND at least one quality feature is weighted, the
final expression is wrapped in `* (1 + RAND() * %(jitter)s)`. Live
feed route (`/`) passes `current_app.config["FEED_JITTER"]`
(default `0.10`) so consecutive refreshes shuffle articles within
~10% score bands. Other callers stay deterministic by default:

- `jobs/send_digest.py` — daily digest must be stable per send.
- `app/routes/firehose.py` — orders by `f.classified_at DESC`, score
  is only there as a per-row tint, jitter wouldn't affect order.
- `app/routes/algo.py` preview — tuning surface where randomness
  would confuse the user.

Env-var `FEED_JITTER=0` disables on prod if needed.

### Known caveat

Jitter is computed per query, so an article on the border between
page N and N+1 could surface on both (or neither) when paginating
via "Load more". Acceptable for v1 — the page-1 refresh experience
is the primary win. A principled per-user "seen-recently downrank"
(impression tracking + N-hour downweight) is now noted under the
Signal Learning roadmap entry as the follow-on.

### Code touched

- `news/app/ranking.py` — `build_score_sql` gains `jitter` kwarg.
- `news/app/config.py` — `FEED_JITTER` default `0.10`.
- `news/app/routes/feed.py` — passes
  `current_app.config["FEED_JITTER"]`.
- `news/tests/test_ranking.py` — 4 new tests
  (`test_jitter_off_by_default`,
  `test_jitter_wraps_score_with_rand_multiplier`,
  `test_jitter_zero_disables_wrap`,
  `test_jitter_skipped_when_no_active_features`). Full suite 182
  passing on this branch.
- `bugs.md` — BUG-012 logged + resolved.
- `roadmap.md` — Signal Learning entry annotated with the
  seen-recently downrank follow-on.

### Server-side state touched

None. No DB change, no migration, no new cron, no new pip dep, no
new symlink. `FEED_JITTER` is an env-var with a working default, so
the default deploy works without touching cPanel env vars. Python
App restart after FTP/CI deploy so the new code loads.

### PR

- **PR #46** (merged 2026-05-13) — Fix BUG-012: refresh-shuffle via
  score jitter.

---

## 2026-05-13 — English-only article filter at fetch time (PR #42)

### Context

User reported non-English articles surfacing in the feed and asked to
restrict to English "for now". The 768-source catalog mixes ~50-100
non-English outlets (FR/DE/JP/HK/ES/NL/IT/KR plus unlabeled tail in
the QA/IN buckets); some US-labeled outlets also syndicate occasional
non-English wire content. Filter has to work per-article, not just
per-source.

### What shipped

- **`app/language.py`** — pure-Python `is_english(title, summary,
  feed_language)`. Two-stage: (1) if the RSS feed's `<language>` tag
  declares a non-English code (e.g., `ja`, `de-DE`), trust it and
  reject; (2) otherwise count letter characters in title+summary and
  reject if the share outside the Latin script ranges (Basic Latin,
  Latin-1, Latin Extended-A/B, Latin Extended Additional) exceeds
  `NON_LATIN_THRESHOLD=0.25`. Permissive by default — empty/None
  inputs accept. No new dependency.
- **`jobs/fetch_feeds.py`** — filter runs before the
  `INSERT IGNORE INTO articles`. Pulls `parsed.feed.language` once
  per feed, checks each entry's title+summary. Rejected entries
  don't insert and don't bump `fresh`/`stale`; instead a new
  `skipped_lang` counter surfaces in the per-tick summary line
  (`fetched=N fresh=N stale=N errors=N skipped_lang=N`) and in
  `pipeline_log`.
- **Per design call** (user-confirmed): existing non-English rows in
  `articles` are left alone. They age out of the 7-day feed window
  naturally and the multiplicative recency gate from BUG-011
  crushes them within ~4 days regardless of static score. No
  backfill purge.
- **Known limitation, documented in INSTALL.txt §10**: Latin-script
  European content (French, German, Spanish, Italian, Dutch, etc.)
  reads as English by the script heuristic and slips through unless
  the feed self-declares a non-English tag. If those leak in
  meaningful volume, next step is either a curated source-language
  column or adding `langdetect` as a dep.

### Code touched

- `news/app/language.py` — new, pure helpers.
- `news/jobs/fetch_feeds.py` — import + per-entry filter + extended
  `fetch_one` return tuple + summary line includes `skipped_lang`.
- `news/tests/test_language.py` — new, 21 cases covering English /
  CJK / Arabic / Cyrillic / Devanagari / Latin Extended accents /
  Vietnamese diacritics / empty inputs / mistakenly-tagged feeds.
- `news/INSTALL.txt` §10 — v1-limit note.
- `roadmap.md` — new Done entry.

### Server-side state touched

None. No DB migration, no new cron entry, no new pip dep, no env-var
change. `fetch_feeds` is a cron entry — it picks up the new module
on its next tick automatically; no Passenger restart strictly
required. Existing non-English `articles` rows stay in the DB and
age out of the feed window over ~7 days.

### PR

- **PR #42** English-only filter at fetch time (merged).

### Open items

- Watch the next few `fetch_feeds` ticks on prod and confirm
  `skipped_lang` is non-zero in cron.log. Sample a few rejected
  domains to make sure we're not over-filtering legitimate English
  content with heavy named-entity non-Latin (e.g., a US news story
  whose title is "Tokyo's 東京 district reopens" should still pass —
  the 0.25 ratio is tuned for that).
- If French/German/Spanish content is the bulk of remaining
  leakage, follow up with either source-level `language` tagging or
  a `langdetect` dep.

---

## 2026-05-13 — Story dossier v1 at `/story/<id>` (PR #43)

### Context

Roadmap Pri 9 / LOE 6 — the "killer demo" item from the dossier chain.
Article deduplication (PR #24) already populates `articles.story_id`,
so the cluster set exists; this PR builds the user-facing destination.

### What shipped

- **Schema** — new `story_dossiers` table keyed by canonical
  `articles.id`. Caches the LLM-generated framing summary per
  cluster-member signature (sha1 of sorted member ids); when the
  cluster gains/loses a member, the signature shifts and the route
  regenerates on the next view. Stored fields: `summary_text`,
  `article_count`, `lean_buckets` ("LCR" subset present), `model`,
  `generated_at`. Migration at
  `seed/migrations/2026-05-13-story-dossiers.sql`.
- **Route** — `GET /story/<int:story_id>` registered as a new
  `story_bp` blueprint at the root mount. Validates the id is a
  canonical cluster row (`articles.id == articles.story_id`), loads
  members from the last 14 days honoring `sources.owner_id` visibility
  (anon sees only global; signed-in additionally sees own personal
  feeds), groups by political-lean bucket (`<=-0.2` left, `>=+0.2`
  right, else center), and renders. Singleton clusters 404 per spec
  ("single-source stories don't get a dossier").
- **Framing summary** — new `app/classifier/framing.py` ·
  `generate_framing(members, *, api_key, model, max_members=12)`.
  Single Haiku call with a tight system prompt asking for 2-4
  sentences of neutral framing commentary. Cost-gated on the route
  side: only fires when `len(members) >= 3 AND distinct lean buckets
  >= 2`. Cache-by-signature means repeat dossier views are free; only
  cluster-set changes trigger a new call. Anthropic SDK imported
  lazily, all failures raised as `LLMUnavailable`; the route catches
  and renders the page without a summary so a missing API key never
  500s.
- **Template** — `templates/story.html`. Serif title, sticky framing
  panel at top, three-column desktop layout (collapses to one column
  under 800px). Each card carries source name, lean dot, headline,
  lead paragraph (prefers `article_bodies.body_text` first paragraph
  >=40 chars; falls back to `articles.summary`), and a "Read →" link
  into the in-app reader. The original-source link on the source name
  + title fires the existing `feed.click` tracking POST.
- **Feed integration** — `feed_cards.html` gets a "+N angles" pill in
  the card meta row when `cluster_size > 1`, linking to
  `/story/{story_id}`. The feed query already exposes `cluster_size`
  and `story_id` (added with PR #24), so no SQL changes.
- **CSS** — `.card-meta .dossier-link` pill style + `.dossier-*` rules
  appended to `style.css`.
- **Tests** — 22 new across two files:
  - `tests/test_story.py` (13) — covers 404 paths (unknown id, non-
    canonical, singleton), two-member render without framing,
    eligibility threshold (3+ members, 2+ buckets), cache hit on
    matching signature skips LLM, cache miss on stale signature
    regenerates, `LLMUnavailable` falls through gracefully, single-
    bucket cluster skips framing, lean-bucket boundaries, signature
    stability across order permutations, lead-paragraph fallback.
  - `tests/test_framing.py` (9) — covers happy path, code-fence
    stripping, no-api-key / empty-members / API exception /
    unparseable JSON / empty summary all raising `LLMUnavailable`,
    member cap, lead truncation. The Anthropic SDK is stubbed via
    `sys.modules` so the suite still passes without the package
    installed (matches the existing `feedparser` stub pattern in
    `test_user_sources.py`).
  - Full suite: 137 passing on this branch after rebase onto main
    (was 132 after PR #38; +5 net after deduplication with concurrent
    work).

### Code touched

- `news/seed/schema.sql` — `story_dossiers` table.
- `news/seed/migrations/2026-05-13-story-dossiers.sql` — new.
- `news/app/classifier/framing.py` — new helper.
- `news/app/classifier/__init__.py` — export `generate_framing`.
- `news/app/routes/story.py` — new blueprint.
- `news/app/__init__.py` — register `story_bp` (no url_prefix; route
  is `/story/<id>` at the root mount).
- `news/app/templates/story.html` — new.
- `news/app/templates/partials/feed_cards.html` — `+N angles` link in
  card meta when `cluster_size > 1`.
- `news/app/static/style.css` — `.dossier-*` rules + the card pill.
- `news/tests/test_story.py`, `news/tests/test_framing.py` — new.

### Server-side state touched

- **Migration pending on prod**: run
  `seed/migrations/2026-05-13-story-dossiers.sql` against
  `lt1ih6uyy2z6_news` via phpMyAdmin **before merging this PR**. The
  route's `_get_or_generate_framing` writes to `story_dossiers` on
  the first uncached view; without the table the first dossier-with-
  framing view would 500. Tracked in `manual-actions.md` with the
  inline SQL.
- No new cron entries, no new env vars, no new symlinks, no new
  dependencies. Anthropic SDK is already in `requirements.txt`
  (used by `classify_pending`); framing reuses the same client and
  API key. Post-merge: restart the Python App so the new blueprint
  registers.

### Notes for next session

- **Cost shape**: with cache-by-signature, a dossier view is one
  Haiku call ($0.001-0.003) per cluster-signature transition. A
  cluster that stops gaining members is effectively free thereafter.
  No backfill / prewarming job — viewing a dossier is what triggers
  generation. If popular dossiers see high read traffic on cold
  clusters, a maintenance.py prewarmer (top-N clusters by
  cluster_size each night) is the obvious follow-on.
- **Word-level diff highlights** between headlines (the
  screenshot-worthy power feature called out in roadmap detail) are
  deferred. Same with per-cluster trending integration.
- **Across-the-spectrum in-feed (Pri 7, LOE 3)** is the next
  natural slice — same `cluster_size` + `story_id` plumbing, but as
  an inline expander on the feed card rather than a destination
  page. Effectively free once dossier exists.

### PR

- **PR #43** — Story dossier (merged). DB migration applied on prod
  (`story_dossiers` table) and Python App restarted.

---

## 2026-05-13 — Mobile / responsive polish (PR #40)

### Context

Roadmap Pri 7 / LOE 4. The roadmap note flagged that "the card grid
wraps OK on phone widths but the algo editor is a mess, the firehose
table is a horror, and tap targets are small." Audit pass at 375px
width confirmed all three plus several smaller issues (top nav
overflow, cramped `.feature-row`, fixed-width admin sidebar, small
`.cat-tab` / `.thumb-btn` tap targets).

### What shipped

- **Single mobile media block** (`@media (max-width: 640px)`) appended
  to `app/static/style.css`. Additive only — desktop layout is
  untouched. Covers:
  - `.topnav` wraps; the brand goes on its own row so the 6–8 nav
    links don't overflow horizontally.
  - `main` padding tightened (1.5em 1.2em → 1em 0.8em) to recover
    horizontal pixels.
  - `.cards` forced to `1fr` single column with a taller card thumb
    (160 → 180px) since each card now spans full width.
  - `.card-meta` items wrap so source / lean / category / time /
    thumbs / reader-link don't fight for one row.
  - `.algo` collapses `1fr 360px` to `1fr`; sticky preview goes
    static so the editor isn't covered. `.feature-row` switches from
    `12em 1fr 1fr 1fr` to a single stacked column (label → direction
    → weight → threshold), which makes the sliders comfortably wide.
  - `.firehose-header` wraps cleanly (no more `space-between`
    blow-out with the long muted explainer). The table keeps all 10
    columns at `min-width: 640px` and `#firehose-feed` gets
    `overflow-x: auto`, so the table scrolls horizontally rather
    than getting squashed.
  - `.admin` stacks; `.admin-nav` becomes a horizontal wrap row;
    `.feed-add` `repeat(4, 1fr)` → `1fr 1fr`; `.data-table` wrapped
    in its own block scroll.
  - Tap targets enlarged on `.cat-tab`, `.thumb-btn`, `.tabs button`.
  - `.auth-form` / `.onboarding` margins tightened.
  - `.preset-card` stacks instead of side-by-side.
- **No template structural change.** All firehose scroll behavior is
  driven by the CSS rules on `#firehose-feed` + `.firehose-table`,
  so the htmx-swapped partial doesn't need a wrapper edit.
- **`.table-scroll`** utility class added globally for any future
  hand-wrapped scrollable table.

### Code touched

- `news/app/static/style.css` — `.table-scroll` utility + single
  `@media (max-width: 640px)` block appended.
- `roadmap.md` — Mobile / responsive polish flipped to `in-progress`.

### Server-side state touched

None. CSS-only deploy — no migration, no cron change, no env-var,
no symlink, no pip dep. Python App restart not required (static
files are served direct off disk by LiteSpeed); FTP/CI deploy is
enough for the new CSS to land.

### PR

- **#40** Mobile / responsive polish (merged) — CSS-only. No DB
  change, no cron, no env-var, no pip dep. FTP/CI deploy enough;
  Python App restart not required.

### Open items

- Spot-check on a real phone (or Chrome devtools at 375px / iPhone
  SE preset) once deployed: `/`, `/algo`, `/firehose`, `/sources`,
  `/account/settings`, `/admin/feeds`, `/admin/discovery`.
- `.feature-row` jumps from stacked (mobile) to 4-col (desktop)
  abruptly at exactly 641px. Acceptable for v1; revisit if a
  tablet-width intermediate layout is needed.

---

## 2026-05-13 — Automated source discovery: Reddit/HN harvest + LLM agent + admin review (PR #38)

### Context

User asked for "an automated feature that discovers new feeds, blogs
and news articles" running on cron. Existing `fetch_feeds` only polls
known sources; the source catalog was previously grown via manual seed
CSV imports (e.g. the +633 batch in PR #11). Goal: a self-driving loop
that proposes new sources from external signals, validates them, and
queues them for admin approval — so the catalog grows continuously
without me hand-editing CSVs.

User picked: Reddit/HN submitted URLs + LLM-agent suggestions as
signals; admin review queue first; hourly harvest + nightly
promotion. Social firehoses (Mastodon, Bluesky, X/Twitter) are
roadmapped as a separate phase 3 PR.

### What shipped this session

- **New `candidate_sources` table.** Single row per unknown domain
  with `score` (hit count), `state ∈ {pending, validated, approved,
  rejected, blacklisted}`, `first_seen_via` / `last_seen_via`,
  `feed_url` / `name` / `homepage_url` / `category` filled in once a
  feed is discovered, and `promoted_source_id` back-linking the
  `sources` row created on approval. UNIQUE on `domain` so signals
  from different harvesters increment the same counter.
- **`jobs/discover_harvest.py`** (hourly cron). Re-polls the same
  Reddit subs + HN top stories that `popularity_poll` visits, then
  upserts every URL whose domain isn't already in `sources` (or
  already-decided in `candidate_sources`). Bumps score by hit count
  per tick. Same `requests.Session` + `(5, 10)` timeouts pattern as
  the rest of the cron stack; `conn.ping(reconnect=True)` after the
  HTTP fan-out, before writes (BUG-009 lesson).
- **`jobs/discover_llm.py`** (weekly cron, Mondays 05:00 UTC). For
  each category in `DISCOVER_LLM_CATEGORIES` (default world / politics
  / tech / science / business / sports), calls Claude Haiku with a
  prompt asking for N high-quality RSS feed URLs we don't already
  have, including a sample of 40 existing domains in the prompt as
  negative context. Parses suggestions out of strict JSON with a
  URL-fishing fallback for sloppy responses. Hallucinated URLs are
  filtered downstream by the nightly validator. Tracks usage in
  `llm_usage`. Safely no-ops if `ANTHROPIC_API_KEY` is absent.
- **`jobs/discover_promote.py`** (nightly cron, 04:00 UTC). Pulls
  pending candidates with `score >= DISCOVER_PROMOTION_SCORE_MIN` (3)
  or an LLM-suggested `feed_url` already set, then runs
  `app.discovery.discover_feed_url(domain)` over a
  `ThreadPoolExecutor(max_workers=8)`. Auto-discovery tries
  `/feed`, `/rss`, `/feed.xml`, `/rss.xml`, `/atom.xml`, `/feed/`,
  `/feeds/posts/default`, `/index.xml` then falls back to parsing
  `<link rel="alternate" type="application/rss+xml">` from the
  homepage. Success → state='validated' with feed_url/name/homepage;
  failure → state='rejected' with reject_reason. Wallclock-budgeted
  at 1500s (cron is `0 4 * * *` so the budget can ride longer than a
  5-min tick).
- **`/admin/discovery`** review page. Three sections — "Ready to
  review" (validated, with per-row Approve form taking name /
  category / country / region / lean / reputation overrides),
  "Pending validation" (still accumulating score), "Recent decisions"
  (14-day audit trail). Approve writes to `sources` and links back
  via `promoted_source_id`. Reject and Blacklist flip state; the
  hourly harvest skips approved/rejected/blacklisted domains so
  rejected-once stays out unless an admin manually re-pendings it.
- **`app/discovery.py`** — pure Flask-free helpers
  (`extract_domain`, `discover_feed_url`, `try_feed_url`,
  `extract_urls`). Matches the convention of `feed_validation.py` and
  `extractor.py` for testability. Includes a small `DOMAIN_BLOCKLIST`
  for social/aggregator/marketplace domains that shouldn't be
  candidates (youtube.com, twitter.com, github.com, amazon.com,
  etc.).
- **Tests.** 20 new (`test_discovery.py`): extract_domain
  normalization × 6, extract_urls × 2, discover_feed_url scripted
  flow × 5, count_new_domains pure dedup × 2,
  parse_llm_response × 5. Full suite is 132 green on this branch
  (was 112 before; the +20 are the new file).

### Code touched

- `news/seed/schema.sql` — `candidate_sources` table.
- `news/seed/migrations/2026-05-13-discovery.sql` — new.
- `news/app/discovery.py` — new, pure helpers.
- `news/app/config.py` — DISCOVER_* env-var defaults.
- `news/jobs/discover_harvest.py`, `discover_llm.py`,
  `discover_promote.py` — new cron scripts.
- `news/app/routes/admin.py` — `/admin/discovery` + three POST
  routes (approve, reject, blacklist).
- `news/app/templates/admin/discovery.html` — new.
- `news/app/templates/admin/_layout.html` — Discovery nav link.
- `news/app/static/style.css` — `.discovery-actions` rules.
- `news/INSTALL.txt` — three cron lines in §4c, troubleshooting
  entry §8I, v1-limit note in §10.
- `news/tests/test_discovery.py` — new, 20 cases.

### Server-side state touched

- **Migration pending on prod**:
  `seed/migrations/2026-05-13-discovery.sql`. Tracked in
  `manual-actions.md` with full inline SQL. The three discover_*
  cron jobs will error on every tick until this table exists.
- **Three new cron entries pending**: discover_harvest hourly,
  discover_promote nightly 04:00 UTC, discover_llm weekly Monday
  05:00 UTC. All wrapped in `job_lock` so they no-op safely if the
  previous tick is still running. Tracked in `manual-actions.md`.
- No new pip dependencies — the LLM job reuses the existing
  anthropic SDK, and the harvest job reuses requests + the stubbed
  feedparser already pulled in by `app.feed_validation`.
- Python App restart required after the migration so the
  `/admin/discovery` route picks up the new table.

### Open items

- Watch the first hourly harvest tick on prod to confirm
  `candidates_upserted` is reasonable (single-digit per tick is
  expected — most Reddit/HN URLs already map to the 768 existing
  sources).
- The first weekly LLM tick will write a `discover_llm` row to
  `pipeline_log` with the per-category suggested/inserted counts;
  worth eyeballing before letting it run unattended.
- BUG-008 hypothesis #2 ("a large portion of the +633 source import
  is dead and auto-deactivated") still uninvestigated. The new
  discovery loop will produce candidates faster than the dead-feed
  cleanup happens; a separate `/admin/feeds` audit pass is worth
  scheduling after the catalog stabilizes.
- Phase 3 (social firehoses — Mastodon, Bluesky, X/Twitter) is in
  the roadmap under "Automated source discovery — social
  firehoses" (Pri 7, LOE 7).

### PR

- **#38** Automated source discovery (Reddit/HN + LLM agent) +
  admin review queue (merged) — DB migration applied on prod, three
  new cron entries added in cPanel (hourly harvest, nightly promote,
  weekly LLM). Python App restarted post-migration.

---

## 2026-05-13 — BUG-011: feed staleness fixed via multiplicative recency gate

### Context

User reported that loading `/` still showed yesterday's articles on
reload — fresh content wasn't surfacing even though the pipeline had
recovered from BUG-009. Originally logged as BUG-010 in this session;
renumbered to BUG-011 on rebase because a parallel session's PR #35
landed BUG-010 first (feature bars).

### Root cause

`app/ranking.py:build_score_sql` summed feature contributions
**additively**. Quality features (objectivity, info_density,
source_reputation, journalist_reputation, etc.) summed to ~3.0 for a
great article; the recency term `recency_w * EXP(-h/24)` capped at
`recency_w` (default 0.7). A 3-day-old high-quality article scored
~3.04; a 1-hour-old medium-quality article scored ~2.2. Static
quality dominated; the top-30 didn't move minute to minute.

### Fix

Changed `recency` from an additive term to a **multiplicative
freshness gate**: `score = quality * EXP(-recency_w * hours / 24)`.
The slider now controls decay strength rather than additive
contribution. With the default `recency=0.7`, multiplier is 1.0 at
fresh, ~0.50 at 24h, ~0.25 at 48h, ~0.05 at 4d, ~0.007 at 7d — a
4-day-old article is structurally crushed regardless of static
quality. `recency=0` opts out (legacy behavior). `feed.py`'s 7-day
window kept; multiplicative decay makes the window self-narrowing.

`weights_to_expression` updated so the `/algo` Code tab's rendered
Python preview matches the new math (`return quality * exp(-r *
hours_old / 24)` instead of an additive recency line).

### Code touched

- `news/app/ranking.py` — `build_score_sql` wraps the quality sum in
  the EXP multiplier when `recency > 0`; `weights_to_expression`
  renders the multiplicative form.
- `news/tests/test_ranking.py` — 3 new tests
  (`test_recency_is_multiplicative_gate`,
  `test_recency_zero_disables_decay`,
  `test_recency_alone_without_quality_features`). Existing
  `test_build_score_sql_includes_active_features` asserts still hold
  (EXP present, recency_w param present).
- `bugs.md` — BUG-011 logged + resolved.

### Server-side state touched

None. No DB changes, no cron changes, no env-var changes, no new
symlinks. Restart Python App from cPanel after merge so the new
ranking module loads.

### PRs

- **PR #34** (merged) — BUG-011: multiplicative recency gate.

### Open items

- None blocking. Verify on prod after restart that `/` shows fresh
  content on reload.
- Possible follow-up: rename the `/algo` slider label from
  "Weight" to "Freshness decay" or similar so its new meaning is
  obvious to users tuning it. Deferred — current label is at worst
  ambiguous, not actively wrong.

---

## 2026-05-13 — BUG-010: feature bars on feed cards rendered identically

User reported "at the bottom of every card is a graphic that is supposed
to show where they rank on each feature, but it doesn't actually work,
so they're all the same."

### Root cause

Template/CSS contract mismatch. `app/templates/partials/feed_cards.html`
set the per-feature bar value via inline `style="width: NN%"`, but
`app/static/style.css:99` makes `.feature-bars i` a flex child with
`flex: 1` — flex children ignore `width` in favor of `flex-grow`, so
the inline value was discarded. The visible fill is actually driven by
the next CSS rule (line 100): `linear-gradient(to right, var(--accent)
var(--w, 50%), #e3e3df var(--w, 50%))`. Nothing in the template ever
set `--w`, so every bar rendered at the `50%` fallback.

### Fix

One-template change: write the value as `style="--w: NN%"` instead of
`style="width: NN%"`. Also added the numeric value to the `title`
attribute so a hover readout shows the actual feature score.

### Code touched

- `app/templates/partials/feed_cards.html` — `width:` → `--w:` on all
  five bars; title tooltip enriched with the numeric value.

### Server-side state touched

None. Restart the Python App after deploy so Jinja reloads cleanly,
though template autoreload usually handles it.

### PR

- **#35** — Fix BUG-010: feature bars used `width:` but CSS expected
  the `--w` custom property (merged).

---

## 2026-05-13 — BUG-008 / BUG-009: classify_pending stalled prod, parallelization restored throughput (PR #32)

### Context

User opened the session with "sauce.ai feels stale" (BUG-008). SSH'd to
prod and pulled the last 80 lines of `logs/cron.log` — every
`classify_pending` invocation since 2026-05-12 22:30 had been dying
with PyMySQL `(2006, "MySQL server has gone away
(ConnectionResetError(104, 'Connection reset by peer'))")` on the
first `INSERT INTO article_features` of the write block. Cron output
stopped entirely at 22:50; `articles` had ~7700 rows stuck in
`status='pending'` that the feed query filters out.

### What shipped this session

- **BUG-009 logged + resolved (PR #32, commit 6857b2b).** Root cause:
  `_run()` opens one PyMySQL connection at the top of the script then
  spends 30–200s per batch on LLM POST + 10× sequential paywall HTTP +
  10× sequential trafilatura body extraction. GoDaddy's shared MySQL
  closes idle sockets aggressively; by the time we reach the writes
  the kernel has RST'd us. Fix: `conn.ping(reconnect=True)` at every
  plausible idle point in `classify_pending`, `popularity_poll`, and
  `fetch_feeds`. PyMySQL transparently re-establishes the connection
  (preserving autocommit) when needed, no-op when alive.
- **BUG-008 resolved (PR #32, commit 6857b2b).** Was hypothesis #3 in
  the original triage ("classify_pending wallclock-starved"). Real
  cause was the script crashing on every tick, not the budget. Once
  reconnect was fixed and the backlog drained, freshness returned.
- **Parallelization shipped (PR #32, commit c2cb2d4).** User asked
  "max the rate." Replaced the two sequential per-article HTTP loops
  (paywall + body extraction) with two `ThreadPoolExecutor(max_workers=10)`
  fan-outs. Bumped urllib3 pool sizes on the shared `requests.Session`
  to 20 to avoid connection-pool serialization. Bumped default
  `CLASSIFY_BUDGET_SECONDS` 90 → 240 (cron is `*/5min` and `job_lock`
  blocks overlap, so 240 s is the safe ceiling). Throughput went from
  10 articles/tick to **180/tick** verified on prod
  (`classified=180 llm_articles=180 cost_usd=0.0533`).

### Code touched

- `news/jobs/classify_pending.py` — ping(reconnect=True) at top of
  each batch iteration + before write block; two HTTP loops replaced
  with ThreadPoolExecutor fan-outs; HTTP_WORKERS=10 module constant;
  HTTPAdapter pool size bump on `requests.Session`; per-future
  try/except so a single slow article can't kill the batch.
- `news/jobs/popularity_poll.py` — ping(reconnect=True) after Reddit+HN
  HTTP, before writes.
- `news/jobs/fetch_feeds.py` — ping(reconnect=True) at the start of
  every `fetch_one`.
- `news/app/config.py` — `CLASSIFY_BUDGET_SECONDS` default 90 → 240.
- `bugs.md` — BUG-009 logged + resolved, BUG-008 resolved.

### Server-side state touched

- Pre-merge: in-place patched 3 cron scripts on prod via SSH heredoc
  (BUG-009 reconnect fix only) to unblock immediately. Backups left as
  `jobs/{classify_pending,fetch_feeds,popularity_poll}.py.bak-<ts>` in
  `~/public_html/sauce.ai/news/`. Once PR #32 merged and the FTP/CI
  deploy ran, the proper merged version (reconnect + parallelization)
  overwrote the in-place patch. The `.bak-` files are no longer
  load-bearing — fine to delete at leisure with
  `rm ~/public_html/sauce.ai/news/jobs/*.bak-*`.
- No new symlinks, no new cron entries, no env-var changes (the
  budget bump is a code default, not a cPanel/crontab env var).
- DB: no schema changes. The pending-backlog (~7700 rows) is draining
  naturally as cron ticks at the new throughput.

### PRs

- **PR #32** (merged) — BUG-008/BUG-009: cron jobs lost MySQL
  connection mid-batch. Reconnect fix + paywall/body parallelization
  + budget bump.

### Open items

- Watch `/admin/feeds` or run `SELECT status, COUNT(*) FROM articles
  GROUP BY status` over the next ~3 hours to confirm the pending
  backlog drains to near-zero. If it stalls, check `cron.log` for
  fresh tracebacks.
- Clean up `~/public_html/sauce.ai/news/jobs/*.bak-*` on prod when
  convenient (just clutter).
- BUG-008 hypothesis #2 ("large portion of +633 source import is dead
  and auto-deactivated") was not investigated this session and remains
  a real possibility worth a separate look once the pipeline backlog
  is fully drained. The freshness symptom may have multiple
  contributors.

### Lesson learned

The wallclock budget exists precisely to keep cron from breaking the
nproc/CPU limit on shared hosting. But the budget being too tight is
much less likely to silently break things than the **assumption that
DB connections survive arbitrary idle periods**. Default to ping-
reconnect for any cron pattern that does HTTP between writes, and put
HTTP fan-outs in parallel from day one.

---

## 2026-05-13 — Session wrap-up: BUG-007 recovery + dep install (PRs #30, #31)

Short recovery-focused session triggered by the user noticing prod was
500'ing after the 20-PR backlog landed. No roadmap items advanced; the
whole session was draining the manual-action queue that had built up
across the previous parallel sessions.

### What shipped this session

- **PR #30** — Logged BUG-007 and resolved it: both outstanding
  `manual-actions.md` Open entries (`sources.owner_id`, `user_signals`
  + `user_source_prefs`) applied to prod via phpMyAdmin; Python App
  restarted; site recovered.
- **PR #31** — Wrap-up: this history entry + manual-actions tracker
  update for the deferred `pip install -r requirements.txt` (PR #21
  trafilatura dependency) that the user completed manually via cPanel
  Terminal after the cPanel "Run Pip Install" button proved disabled.
- Confirmed via `SHOW COLUMNS` / `SHOW TABLES` that the earlier
  pre-tracker migrations were already on prod (`article_features.paywall`
  from PR #14, `article_bodies` from PR #21, `articles.simhash` /
  `story_id` from PR #24, `users.digest_enabled` from PR #23). Schema
  is fully synced as of session end.

### Server-side state at session end

- DB `lt1ih6uyy2z6_news`: all merged-PR migrations applied.
- venv: `pip install -r requirements.txt` run from cPanel Terminal —
  trafilatura now installed, so `classify_pending`'s body extraction
  step will start producing `article_bodies` rows on the next cron tick.
- Python App restarted post-install.
- No new symlinks, no new cron entries, no env-var changes.

### Process note for future sessions

The two-PR-into-prod-without-running-the-migration failure mode is
exactly what the manual-actions tracker (PR #22) was built to prevent,
and the tracker itself worked — the entries were logged the moment
each parent PR landed. The miss was operational, not procedural: the
queue accumulated faster than it drained. Two adjustments worth
considering if this happens again:

- **Drain before merging the next migration-bearing PR.** Treat any
  Open entry in `manual-actions.md` as a blocker on merging another
  one. The tracker is supposed to be near-empty most of the time.
- **Run `SHOW COLUMNS`/`SHOW TABLES` at session start** whenever
  there's been heavy parallel-session activity, to confirm prod
  schema matches what merged code is going to query.

### PRs

- **#30** Log + resolve BUG-007, move both migrations to Completed
  (merged).
- **#31** Wrap-up tracking-doc updates (draft).

---

## 2026-05-13 — BUG-007: prod 500 from pending migrations (PR #30)

After ~20 PRs merged in rapid succession without testing between,
`sauce.ai/news` started 500'ing on every request. Two outstanding
prod migrations from `manual-actions.md` Open section were the cause —
both reference columns/tables that the merged code paths query at
request time.

### What happened

- `feed.py:65` and `firehose.py:49` reference `s.owner_id` in the
  visibility WHERE clause on every page load (anon path included).
  `sources.owner_id` (PR #29) hadn't been applied to prod, so every
  reader route 500'd from a "Unknown column 's.owner_id'" SQL error.
- `feed.py` also LEFT JOINs `user_source_prefs` for signed-in users.
  `user_signals` + `user_source_prefs` (PR #19) similarly hadn't been
  applied; would have 500'd the signed-in feed independently.

### What shipped

- BUG-007 logged in `bugs.md` with status `in-progress` immediately
  on report (per the session-start protocol), then resolved after the
  fix landed.
- Both migrations applied to `lt1ih6uyy2z6_news` via phpMyAdmin;
  Python App restarted; site recovered.
- Both entries moved from Open → Completed in `manual-actions.md`
  with the applied SQL inline.

### Process learning

The lifecycle hook from PR #22 worked exactly as designed — the
migrations were logged in `manual-actions.md` the moment each PR
landed. The gap was that nobody (user or session) actually *ran*
them between merges, so the queue accumulated and the next deploy
went live referencing columns that didn't exist. For high-PR runs:
either run each migration before merging its PR, or batch and run
them with a single Python App restart at the end. Don't trust
"will run later" — `manual-actions.md` Open is a load-bearing
queue, not a memo.

### Code touched

- `bugs.md` — BUG-007 entry (added open → moved to resolved).
- `manual-actions.md` — two entries moved Open → Completed with
  applied-date and applied SQL inline.

### Server-side state touched

- Prod DB `lt1ih6uyy2z6_news`: `sources.owner_id` column +
  `idx_sources_owner` index + `fk_sources_owner` FK added;
  `user_signals` and `user_source_prefs` tables created.
- Python App restarted via cPanel.

### PR

- **#30** Log BUG-007 + tracking-doc updates (draft, ready to mark
  ready-for-review).

---

## 2026-05-13 — Article deduplication across sources (PR #24)

Roadmap item Pri 8 / LOE 7. Surfaces a single canonical card per "story
group" in the main feed; firehose intentionally stays un-deduped. Unblocks
the dossier (Pri 9) and across-the-spectrum-in-feed (Pri 7) work.

### What shipped

- **Schema**: `articles.simhash BIGINT UNSIGNED` (64-bit SimHash) and
  `articles.story_id BIGINT UNSIGNED` (cluster id = canonical member's
  `articles.id`). Indexed on `(story_id, published_at)`. Migration at
  `seed/migrations/2026-05-13-dedup.sql` backfills `story_id = id` for
  legacy rows; SimHash backfill is deferred to runtime since clustering
  only operates over a rolling 48h window.
- **`fetch_feeds.py`**: computes `article_simhash(title, summary)` at
  insert time and sets `story_id = id` immediately after the INSERT (each
  new article starts as its own singleton cluster).
- **`classify_pending.py`**: new `_assign_story_id()` runs per article in
  the batch loop, right before flipping `status='classified'`. Lookup
  order: (1) exact `title_hash` match in last 48h, (2) `BIT_COUNT(simhash
  ^ mine) <= 8` in last 48h. If a candidate exists, compare us to the
  current canonical: higher `source_reputation` (tiebreak: older
  `published_at`) promotes us to canonical and rewrites the whole
  cluster's story_id; otherwise we adopt the existing canonical's id.
- **`feed.py`**: `WHERE a.story_id IS NULL OR a.id = a.story_id` keeps
  only canonicals, plus a `cluster_size` LEFT JOIN subquery rides in
  the result row for future UI (Across-the-spectrum in-feed badge, story
  dossier).
- **`firehose.py`**: left untouched per design call. Firehose is the
  see-everything stream.
- **`maintenance.py`**: nightly heals orphaned story_ids (NULL or pointing
  at a pruned article) by self-assigning.
- **Tests**: 13 new (`test_simhash.py` × 8 for SimHash primitives,
  `test_assign_story_id.py` × 7 for the cluster-assign logic via a fake
  cursor that scripts `fetchone()` returns). All 72 tests pass.

### Calibration notes (worth knowing for v2)

- 64-bit SimHash on title + 200-char summary lead delivers HD≈6-8 for
  syndicated reprints with a re-written headline (typical AP→partner
  outlet pattern). Threshold 8 cleanly separates true near-dups
  (HD 0-8) from unrelated-but-similar-headline content (HD≈18) and
  fully unrelated content (HD≈32).
- **Heavy paraphrases are NOT clustered.** SimHash on short text is
  fundamentally limited; you can't get "Federal Reserve holds rates"
  vs "Powell stays the course" to within HD<=8 without embeddings.
  This is the v2 upgrade path the roadmap calls out — TF-IDF first-pass
  + embeddings on near-matches.
- The cluster-assign cost per article is two indexed SELECTs (the
  title_hash hit short-circuits the SimHash scan ~30-50% of the time
  for AP-wire heavy feeds). Negligible vs the LLM + paywall HTTP work
  already in `classify_pending`.

### Code touched

- `app/classifier/rules.py` — new `simhash64`, `hamming64`,
  `article_simhash`.
- `app/classifier/__init__.py` — export the new helpers.
- `jobs/fetch_feeds.py` — compute SimHash on insert; UPDATE story_id=id
  post-insert.
- `jobs/classify_pending.py` — new `_assign_story_id()`; batch SELECT
  pulls `a.simhash` + `a.published_at`; wire into the per-article
  feature-write loop.
- `app/routes/feed.py` — dedup filter + `cluster_size` join.
- `jobs/maintenance.py` — orphan story_id heal.
- `seed/schema.sql` — new columns + index.
- `seed/migrations/2026-05-13-dedup.sql` — new.
- `tests/test_simhash.py`, `tests/test_assign_story_id.py` — new.

### Server-side state touched

- **Migration applied** (2026-05-13): `seed/migrations/2026-05-13-dedup.sql`
  ran on prod via phpMyAdmin. Python App restart still required when the
  PR merges so the new code path picks up the columns.
- No new symlinks or load-bearing files.

### PR

- **#24** Article deduplication across sources (merged) — DB migration
  applied on prod. Python App restart required post-merge so the new
  code path picks up the columns.

---

## 2026-05-13 — Manual-actions tracker + lifecycle hooks (PR #22)

User-driven convention change: server-side actions (DB migrations,
cron entries, symlinks, env-var changes) were getting buried in
history entries and INSTALL.txt; new sessions kept assuming prod was
caught up when it wasn't.

### What shipped

- **`manual-actions.md`** at repo root. Sections: Open / Completed.
  Each entry carries the **full SQL/command inline** in the doc (not
  just a path to a `seed/migrations/*.sql` file). Pre-seeded with the
  open `user_signals` + `user_source_prefs` migration from PR #19.
- **Session-start hook** (`new-engineering-session-instructions.md`
  Step 2/3): the agent now reads `manual-actions.md` alongside
  `roadmap.md` and `bugs.md`, and at session start asks the user
  whether each Open entry has been completed. Confirmed-done entries
  move to Completed in the agent's first commit.
- **Session-wrap-up hook** (`engineering-session-wrapup.md` new
  Step 6): any session shipping a manual prod action must (a) append
  a new Open entry to `manual-actions.md` with the SQL/commands inline
  and (b) paste the same SQL/commands into chat. Path-only entries are
  explicitly disallowed in the anti-patterns section.

### Code touched

- `manual-actions.md` (new, root).
- `new-engineering-session-instructions.md` (Step 2/3 + tl;dr).
- `engineering-session-wrapup.md` (new Step 6, renumber, anti-pattern).

### Server-side state touched

None.

### PR

- **#22** Manual-actions tracker + lifecycle hooks (merged)

---

## 2026-05-13 — User-added RSS feed subscriptions (PR #29)

Roadmap Pri 6, LOE 4. Signed-in users can paste an RSS or Atom URL on
a new `/sources` page; the URL is validated synchronously (HTTP GET +
feedparser, must yield ≥1 entry) and on success persisted to `sources`
with `owner_id` set. Cron `fetch_feeds` is unchanged — it polls every
active row, so personal sources flow through the same pipeline. Per-user
visibility is enforced at the reader-feed query layer via
`(s.owner_id IS NULL OR s.owner_id = current_user_id)` in `feed.py` and
`firehose.py`.

### Co-existence with other parallel work merged today

This session ran concurrently with the work that landed in PRs #19–#26
(user_signals/thumbs, user_source_prefs, account settings, reader view,
digest emails). All orthogonal:

- `user_source_prefs` weights existing **global** sources up/down per
  user; this PR adds **new personal** sources visible only to the
  owner. The feed query carries both layers — first filters out
  anything outside the user's visibility (this PR), then applies the
  user's source-weight multiplier on what remains (PR #19).
- Shared edits to `app/__init__.py` (blueprint registration),
  `seed/schema.sql`, and `templates/base.html` (nav link) resolved
  cleanly during rebase.

### Code touched

- `app/feed_validation.py` (new, Flask-free) — `validate_feed`,
  `infer_category`.
- `app/routes/sources.py` (new) — `/sources` blueprint, login-required.
- `app/templates/me_sources.html` (new) — add form + status table.
- `app/__init__.py` — register `sources_bp` at `/sources`.
- `app/routes/feed.py`, `app/routes/firehose.py` — `owner_id`
  visibility filter on the article and category-count queries.
- `app/templates/base.html` — "Your Sources" nav link.
- `seed/schema.sql` — `sources.owner_id INT UNSIGNED NULL` + index + FK.
- `seed/migrations/2026-05-13-user-sources.sql` (new) — ALTER for prod.
- `tests/test_user_sources.py` (new, 11 cases).

### Server-side state touched

- **Migration pending on prod**: `2026-05-13-user-sources.sql`. The
  visibility filters reference `s.owner_id`, so the feed and firehose
  pages will 500 until the column exists. Tracked in
  `manual-actions.md` with full inline SQL.

### PR

- **#29** User-added RSS feed subscriptions (draft) — requires manual
  DB migration on prod before merge.

---

## 2026-05-13 — In-app reader view + body extraction (PR #21)

Roadmap Pri 8, LOE 6. Article body is extracted post-fetch into a new
`article_bodies` table and rendered at `/read/<id>` inside our own
typography. Foundational unlock — body text feeds future summary, TTS,
dedup-on-body, and search work.

### What shipped

- **New `article_bodies` table** (separate from `articles` to keep the
  feed-join row lean). Columns: `body_text`, `body_html`, `lead_image`,
  `author`, `word_count`, `extractor`, `status` (`ok|empty|blocked|
  error`), `extracted_at`. Migration
  `seed/migrations/2026-05-13-article-bodies.sql`.
- **`app/extractor.py`** — pure `extract_body(url, *, session, timeout)`
  returns an `ExtractResult` dict. Uses `trafilatura` (lazy import) for
  body + metadata, with a 1 MB HTTP cap and a `MIN_WORDS=60` floor (below
  that → `status='empty'`). HTTP 4xx/5xx → `blocked`; network errors →
  `error`.
- **`jobs/classify_pending.py`** runs extraction immediately after
  paywall scoring, sharing the `requests.Session`. Articles already
  flagged paywall=1.0 are skipped (the fetch would just record an
  `error` row). All steps share the existing `CLASSIFY_BUDGET_SECONDS`
  wallclock budget.
- **`/read/<id>` route** (`app/routes/reader.py`, new blueprint). Joins
  `articles + sources + article_features + article_bodies` and renders
  `templates/reader.html` — large serif title, hero image (lead_image
  falling back to thumbnail), paragraphs split on newlines, ~min-read
  stat, fallback message keyed off `body_status`, "Read at <source>"
  footer link that fires the existing click-tracking POST.
- **Entry point on cards** — single `Read →` link appended to
  `card-meta` in `feed_cards.html`, sitting alongside the thumbs from
  PR #19. Default click behaviour on title/thumbnail anchors is
  unchanged.
- **Nightly prune** in `maintenance.py` deletes from `article_bodies`
  older than `BODY_RETENTION_DAYS` (default 30, env-overrideable).
  Independent of `ARTICLE_RETENTION_DAYS` so bodies can be tightened
  without losing feed history. Bookmark-aware retention can override
  later when `/saved` lands.
- **Safety**: body_html is captured but the template renders only
  `body_text` split into paragraphs. trafilatura's html output isn't
  sanitized for direct injection; bleach pass deferred until needed.

### Code touched

- `app/extractor.py` (new).
- `app/routes/reader.py` (new), `app/__init__.py` (register blueprint).
- `app/templates/reader.html` (new), `app/templates/partials/feed_cards.html`
  (one-line Read link in card-meta).
- `app/static/style.css` (appended `.reader-*` rules + `.card-meta
  .reader-link`).
- `app/config.py` (`BODY_RETENTION_DAYS`).
- `jobs/classify_pending.py` (extraction step + INSERT).
- `jobs/maintenance.py` (body prune).
- `seed/schema.sql` (article_bodies),
  `seed/migrations/2026-05-13-article-bodies.sql`.
- `requirements.txt` (`trafilatura==1.12.2`).
- `tests/test_extractor.py` (10 cases, stubs trafilatura via
  `monkeypatch.setitem(sys.modules, ...)`).
- `INSTALL.txt` §10.

### Server-side state touched

- **Migration pending**: run
  `seed/migrations/2026-05-13-article-bodies.sql` via phpMyAdmin before
  the next classify_pending cycle, otherwise the new INSERT errors.
- **New dependency**: `trafilatura==1.12.2`. `pip install -r
  requirements.txt` on cPanel after deploy. Restart the Python App
  once the migration and dependency are in place.

### Open items

- Per-user setting "card click goes to reader vs. source" is the next
  slice of this theme — now that thumbs (#19) have landed alongside,
  the card body has the surface area for it.
- `body_html` is stored but unused by the template. A bleach pass +
  formatting-preserving render is a follow-up.
- Bookmark-aware retention waits on `/saved`.

### PR

- **#21** In-app reader view + body extraction (merged)

---

## 2026-05-13 — Thumbs up/down on cards + signal foundation (PR #19)

Shipping the cheapest explicit reader signal (thumbs) and laying the
generic `user_signals` table that the Pri-8 Signal Learning roadmap item
will consume next. Includes the roadmap-called-out side effects:
"3+ downs from {source}" prompt + per-user-source downweight/hide.

### What shipped

- **`user_signals` table** (new) — generic, forward-compat for the full
  Signal Learning vocabulary (`thumb_up`, `thumb_down`, `save`, `share`,
  `hide`, `dwell_ms`, `scroll_pct`, `return_click`). `value` is NULL for
  binary signals; numeric for magnitude-bearing ones. Unique constraint
  on `(user_id, article_id, signal_type)` makes toggle an INSERT/DELETE.
- **`user_source_prefs` table** (new) — per-user-source weight. Missing
  row = 1.0 (default). `weight=0` hides the source from the feed;
  anything `<1` downweights.
- **New `/signal` blueprint** with two routes:
  - `POST /signal/<article_id>/<thumb_up|thumb_down>` — toggle semantics
    (same thumb twice undoes; opposite thumb replaces). Returns JSON
    `{state, prompt}`. After a thumb-down, if the user has ≥3 downs
    from that source in the last 30 days AND has no existing pref row,
    `prompt` carries `{source_id, source_name, down_count}` for the UI.
  - `POST /signal/source/<source_id>` body `{action: hide|downweight|reset}`
    — writes `user_source_prefs.weight` (0, 0.5, or DELETE row).
- **Feed query integration** in `feed.index()` only — keeps the algo
  system in `ranking.py` untouched. For signed-in users: LEFT JOIN
  `user_source_prefs`, filter `COALESCE(usp.weight, 1.0) > 0`, multiply
  score by `COALESCE(usp.weight, 1.0)`. Anon users get the existing
  unmodified query.
- **UI on feed cards** — subtle `▲`/`▼` chevrons in the card meta row,
  hover-revealed (opacity 0.25 → 0.75 on card hover, 1.0 when active).
  Active state colors: up green, down red. Anon users see no thumbs.
  Alpine.js `cardSignals(...)` factory lives in `feed.html`; after a
  down that triggers the prompt, an inline yellow strip appears under
  the feature bars with three actions: Less / Hide / Dismiss.
- **HTMX + Alpine re-init** — `htmx:afterSwap` hooks `Alpine.initTree`
  on the swapped target so the "Load more" cards are reactive too.

### Code touched

- `news/seed/schema.sql` — `user_signals`, `user_source_prefs`.
- `news/seed/migrations/2026-05-13-signals.sql` (new) — same two tables.
- `news/app/routes/signals.py` (new).
- `news/app/__init__.py` — blueprint registration.
- `news/app/routes/feed.py` — pref JOIN + thumb attach.
- `news/app/templates/partials/feed_cards.html` — thumb buttons + Alpine
  data + source prompt.
- `news/app/templates/feed.html` — `cardSignals` JS + HTMX init hook.
- `news/app/static/style.css` — `.thumbs`, `.thumb-btn`, `.source-prompt`.
- `news/tests/test_signals.py` (new, 13 cases).

### Server-side state touched

- **Migration pending:** `seed/migrations/2026-05-13-signals.sql` must
  run on prod via phpMyAdmin before the new code goes live, otherwise
  the signal route INSERTs error. Followed by a Python App restart.

### PR

- **#19** Thumbs up/down on cards + signal foundation (merged) — requires manual DB migration

---

## 2026-05-13 — Daily personalized email digest (PR #23)

Roadmap item shipped: Daily personalized email digest (Pri 6, LOE 7).

### What shipped

- **Opt-in only.** New `users.digest_enabled` flag (default 0). Users
  toggle on `/account/settings`. A 40-hex `digest_unsub_token` is
  minted lazily on first opt-in and stored on the user row. Each
  email's `List-Unsubscribe` header points at
  `/account/unsubscribe/<token>` (one-click via
  `List-Unsubscribe-Post`); the unsubscribe route flips
  `digest_enabled=0` and rotates the token so the link can't be
  replayed.
- **Cron job `jobs/send_digest.py`** wrapped in `job_lock("send_digest")`.
  Selects users with `digest_enabled=1` AND
  (`digest_last_sent_at IS NULL` OR older than
  `DIGEST_RESEND_GUARD_HOURS` (default 20h)). Per user: loads the active
  `user_algorithms` row, reuses `app.ranking.build_score_sql` /
  `build_filters_sql` so digest ranking matches the live feed,
  scopes to `DIGEST_LOOKBACK_HOURS` (default 24h), caps to
  `DIGEST_MAX_ARTICLES` (default 8). Skip-empty for users whose
  ranking returns nothing in the window. Updates
  `digest_last_sent_at` only on successful send; one user's failure
  rolls back its transaction and continues the loop.
- **SMTP via stdlib `smtplib`.** Defaults to `localhost:25` (cPanel's
  local MTA). `SMTP_USE_TLS=1` enables STARTTLS; `SMTP_USER`/`SMTP_PASSWORD`
  enable auth. `SMTP_FROM` defaults to `news@sauce.ai`. No new pip
  dependency.
- **Templates.** `digest_email.html` (inline-styled, serif wordmark
  matching PR #13) + `digest_email.txt` (plaintext fallback). Both
  rendered through a Jinja `Environment` built from
  `app/templates/`; `render_digest` is decoupled from Flask so it's
  unit-testable without spinning up the app.
- **Account blueprint.** New `app/routes/account.py` mounted at
  `/account`: `GET/POST /settings` (login-required toggle),
  `GET/POST /unsubscribe/<token>` (token-gated, no login).
  `base.html` gets a single "Settings" link in the logged-in nav.
- **Tests.** `tests/test_digest.py` (6 cases): SQL shape +
  lookback/limit/weight params, empty-weights still queries,
  multipart HTML+text render with article fields and unsubscribe URL
  in both parts, subject includes article count, SMTP STARTTLS
  path, SMTP plain local-MTA path. Full suite 61 passing.

### Code touched

- `seed/schema.sql` — users gets `digest_enabled`,
  `digest_unsub_token`, `digest_last_sent_at`, plus
  `idx_users_digest`.
- `seed/migrations/2026-05-13-digest.sql` (new).
- `app/config.py` — SMTP_* + DIGEST_* + SITE_URL.
- `app/__init__.py` — register account blueprint.
- `app/routes/account.py` (new) — settings + unsubscribe.
- `app/templates/account_settings.html`, `unsubscribed.html`,
  `digest_email.html`, `digest_email.txt` (new).
- `app/templates/base.html` — one-line Settings link.
- `jobs/send_digest.py` (new) — cron entry, job_lock, render +
  smtp_send + select_articles, batched per user.
- `tests/test_digest.py` (new, 6 cases).
- `INSTALL.txt` — env-vars block (optional SMTP_*), new cron line,
  v1 limitation note re deliverability, troubleshooting §8H.

### Server-side state touched

- **Migration pending**: `seed/migrations/2026-05-13-digest.sql`
  must run via phpMyAdmin before any user toggles digest on,
  otherwise the `/account/settings` POST errors.
- **New cron entry** (noon UTC daily) per INSTALL §4c. Safe to add
  before anyone opts in — runs as a no-op until then.
- **New env vars** (optional, see INSTALL §2b) only required if
  relaying through a real SMTP provider rather than cPanel's local
  MTA.

### PR

- **#23** Daily email digest (merged) — requires manual DB migration + new cron entry.

---

## 2026-05-13 — Cron job hardening + PyMySQL timeouts (PR #15)

Stabilization pass on the pipeline. Two roadmap items shipped together
because they touch the same surface (cron entrypoints + connection
setup): Cron job hardening (Pri 8, LOE 3) and PyMySQL connection
timeouts (Pri 8, LOE 2).

### What shipped

- **Per-job mutex.** New `job_lock(name)` context manager in
  `jobs/_bootstrap.py` uses `fcntl.flock` on per-job lockfiles under
  `news/logs/`. Each cron `main()` wraps its body. Overlapping cron tick
  (e.g. `classify_pending` running long because the LLM stalled) now
  exits as a no-op instead of stacking. Directly addresses the
  CloudLinux nproc-exhaustion failure mode.
- **Request timeouts on every external call.**
  - `fetch_feeds`: replaced `socket.setdefaulttimeout(20)` with explicit
    `requests.get(url, timeout=(5, 15))`, bytes handed to
    `feedparser.parse`. Shared `Session` across the batch.
  - `popularity_poll`: shared `Session`, `(5, 10)` timeout, wallclock
    budget `HN_BUDGET_SECONDS=60` on the per-item HN walk.
  - `app/classifier/llm.py`: `timeout=30.0` on `messages.create`.
- **PyMySQL timeouts** on both `pymysql.connect` callsites in
  `app/db.py`. Web path `(5, 15, 10)`, cron path `(5, 30, 15)` (cron
  does heavier batch INSERTs, especially now that classify_pending also
  HTTP-probes for paywall).
- **`FEED_FETCH_BATCH` default 80→20** per roadmap. With the new
  per-source timeouts the original 80 is probably fine; raise via cPanel
  env var if cron logs show idle wallclock.
- Deferred `app.db` import inside `_bootstrap.get_conn()` so the lock
  helper can be tested without dragging in pymysql.
- `.gitignore` covers `news/logs/*.lock`.

### Code touched

- `jobs/_bootstrap.py` (new `job_lock` + `AlreadyRunning`; deferred db
  import).
- `jobs/fetch_feeds.py`, `classify_pending.py`, `popularity_poll.py`,
  `maintenance.py` — wrap `main()` in `job_lock`; resource cleanup.
- `app/db.py` — PyMySQL timeouts.
- `app/classifier/llm.py` — anthropic timeout.
- `app/config.py` — `FEED_FETCH_BATCH` default.
- `tests/test_job_lock.py` (new, 4 cases).
- `.gitignore`.

### Server-side state touched

- No DB changes. No migration. Restart the Python App so the new code
  loads. New lockfiles appear in `news/logs/` automatically on each
  job's next tick.

### PR

- **#15** Cron hardening + PyMySQL timeouts (merged)

---

## 2026-05-13 — Session wrap-up

Three PRs shipped this session (#13, #14, #15). Two manual prod actions
were required during the session and are confirmed done: import the
+633 sources via `/admin/feeds`, and run the paywall column migration.
The cron-hardening PR (#15) needs only a Python App restart.

PRs in this session:
- **#13** Editorial serif wordmark in topnav.
- **#14** Paywall feature (per-article detection) — required DB migration.
- **#15** Cron hardening + PyMySQL timeouts — no DB change, restart only.

Open follow-ups:
- Manual: verify the +633 sources have cycled through `fetch_feeds` and
  sort `/admin/feeds` by `error_count` to clean up dead URLs.
- Roadmap top: Article deduplication (Pri 8), CSRF + auth rate limiting
  (Pri 7), Fold internal clicks into popularity (Pri 7), Mobile polish
  (Pri 7). Sandboxed Python algo execution (Pri 9) is the big one but
  also the highest LOE.

---

## 2026-05-12 — Paywall feature: active per-article detection (PR #14)

New `paywall` ranking feature so users can down-weight or hard-filter
articles behind subscription walls.

Detection is active per-article during `classify_pending`: HTTP GET with
an 8s timeout, check for JSON-LD `isAccessibleForFree: false`, NYT-style
`<meta property="article:content_tier">`, and paywall phrases on short
bodies. Scoring (0..1):
- `1.0` — JSON-LD or `content_tier` locked/paid/subscriber
- `0.8` — paywall phrase on body < 8 KB
- `0.6` — `content_tier=metered`
- `0.5` — blocked / 4xx / 5xx / timeout / short body, no phrase (suspected)
- `0.0` — long body, no signals (assumed free)

Product call: sites that won't let us in score 0.5 (suspected) rather
than 0.0. A discerning reader who wants to avoid paywalls is better
served by a conservative default than by letting unverified articles
through.

Catalog entry: unsigned, default direction 0.0 (prefer free), default
weight 0.0 (opt-in — existing user algos unchanged). Threshold ~0.2 hides
anything but fully free.

Schema: new `article_features.paywall FLOAT` (default 0). Migration at
`news/seed/migrations/2026-05-12-paywall.sql`. Score SQL + threshold
filter pick up the new column automatically because both iterate over
`FEATURES`. `algo.html` renders the new control via the same loop.

`/admin/feeds` gains a Paywall column — rolling 7-day mean per source,
color-coded green/amber/red.

Pipeline cost: classify_pending now does one HTTP GET per article in
addition to the rules + LLM batch work. The loop honours
`CLASSIFY_BUDGET_SECONDS` so a stuck site can't blow a cron tick.
Articles cut off by the budget get `paywall=0.5` (same as live blocks).
Cron job hardening on the roadmap (Pri 8, LOE 3) would tighten this.

### Code touched

- `app/classifier/paywall.py` — new module, `detect_paywall(url)`.
- `app/classifier/__init__.py` — export.
- `jobs/classify_pending.py` — wired in detector, added `requests.Session`,
  paywall column in INSERT.
- `app/ranking.py` — `paywall` in `FEATURES`.
- `app/routes/admin.py`, `templates/admin/feeds.html`, `static/style.css`
  — admin paywall column + color coding.
- `seed/schema.sql`, `seed/feature_catalog.sql`,
  `seed/migrations/2026-05-12-paywall.sql`.
- `tests/test_paywall.py` (12 cases), `tests/test_ranking.py` (3 new).

### Server-side state touched

- **Migration pending**: `seed/migrations/2026-05-12-paywall.sql` must
  run on prod via phpMyAdmin before the next classify_pending cycle,
  otherwise the INSERT errors. Followed by a Python App restart.

### PR

- **#14** Paywall feature (merged) — requires manual DB migration

---

## 2026-05-12 — Editorial serif wordmark in topnav (PR #13)

User wanted "a very, very subtle hint of personality" on the title/logo —
"high-intelligence... sophisticated simplicity, for the discerning reader."

Restyled the `.brand` element in `base.html` only. `sauce.ai` now renders in
a system serif stack (`ui-serif`, "Iowan Old Style", "Charter",
"Source Serif Pro", Georgia); the `/` separator is muted gray with light
spacing; `news` is set in serif italic. Weight 500 roman / 400 italic, size
1.05em. The rest of the UI keeps the system sans.

Implementation is two-file:
- `app/templates/base.html` — split brand text into `sauce.ai`,
  `<span class="brand-slash">/</span>`, `<em>news</em>`.
- `app/static/style.css` — extended `.topnav .brand` rule + two child
  selectors. No new assets, no JS.

No server-side state touched.

### PR

- **#13** Editorial serif wordmark in topnav (merged)

---

## 2026-05-12 — Feature batch: bug fix, category tabs, 3-axis config, obscurity, +633 sources

User-reported batch of features and one bug. Five PRs (#7–#11) all merged.
Site is live, pipeline healthy.

### PR #7 — Fix BUG-006 (article clicks) + queue roadmap items

The two `<a>` tags in `feed_cards.html` had `hx-post` for click-tracking,
which HTMX intercepts with `preventDefault()`. Tracking POST fired but the
browser never followed `href`, so articles never opened. Switched to
vanilla `onclick="fetch(..., {method:'POST', keepalive:true})"` — browser
navigation works normally and the tracking request survives page unload
via keepalive. Firehose template already used plain anchors; no change
needed there.

Roadmap got four new entries marked in-progress (3-axis config, +500
sources, obscurity, category tabs).

### PR #8 — Category tabs on `/`

Pill-style tabs above the feed cards, sourced from distinct categories in
`article_features` over the last 7 days, ordered by article count desc.
Empty categories don't show. "All" tab clears the filter. URL: `?category=X`.
HTMX "Load more" preserves the active category through pagination.
Hard filter on the SQL; doesn't interact with the user's algo weighting.

### PR #9 — 3-axis feature config (Direction + Weight + Threshold)

Replaced the per-feature `{weight}` / `{weight, target}` model with a
uniform three-axis config:
- **Direction**: where on the feature's scale you want articles
- **Weight**: 0..2 soft contribution
- **Threshold**: optional hard filter (`|value - direction| <= threshold`)

Score formula is now uniform: `weight * (1 - |value - direction| / scale)`.
For unsigned features with direction=1 this reduces to the old
`weight * value`, so pre-existing user weights still work unchanged
without migration.

Touches `app/ranking.py` (new `FEATURES` catalog + uniform score/filter),
`app/routes/algo.py` (centralized form parsing + view resolver),
`app/templates/algo.html` (three controls per row with per-feature
low/high labels), CSS, all four `PRESETS`, and tests (28 → 36 passing).

### PR #10 — Obscurity features (story + source)

Two new ranking features:
- **`source_obscurity`** = log-scaled inverse of 30-day publication
  volume. Tiny outlets → 1.0, ~1000/30d → 0.
- **`story_obscurity`** = log-scaled inverse of how many articles share
  the same normalized title (SHA1) over the last 24h. Only-this-story →
  1.0, ~20 sources → 0. Coarse v1; will improve once the dedup roadmap
  item lands.

Schema additions (manual migration required for existing installs):
- `articles.title_hash` CHAR(40) + index
- `sources.article_count_30d` INT
- `article_features.story_obscurity` / `source_obscurity` FLOAT

Migration shipped at `news/seed/migrations/2026-05-12-obscurity.sql` —
applied successfully on prod during the session.

`fetch_feeds` hashes titles at insert time; `classify_pending` reads
`article_count_30d` and computes both scores per batch (one grouped
query for story counts); `maintenance.py` recomputes nightly so story
clusters update as more articles arrive.

Both features default to `weight=0` in the catalog, so existing user
algos opt in.

### PR #11 — Source catalog +633 + auto-deactivate + Refresh button

Curated 633 net-new RSS feeds into `seed/source_lean.csv` (135 → 768).
Coverage across `world / politics / general / tech / science / business /
sports` and geographically across US/GB/EU/JP/IN/HK/SG/KR/AU/CA/ZA/NG/EG/KE
plus a "QA" placeholder bucket for misc international.

⚠ Feed URLs are best-effort from memory; non-zero rate of 404s and parse
errors is expected on first cron cycle. Mitigations shipped in the same PR:
- `fetch_feeds` SELECT skips sources with `error_count >= 10`
- On the 10th consecutive failure the source flips to `is_active=0`
- New `POST /admin/feeds/<id>/refresh` route + button on `/admin/feeds`
  that synchronously re-polls the URL. On success, resets `error_count=0`
  + `is_active=1`. On failure, increments `error_count` like the cron
  path.
- Delete button was already in the template + route; verified working.

### Server-side state touched

- `seed/migrations/2026-05-12-obscurity.sql` applied via phpMyAdmin
  during the session.
- Python App restarted post-migration.
- 633 new sources to be imported via `/admin/feeds` → "Import / refresh
  seed CSV" — **still pending on the user**.

### Open items / next session candidates

- Manual: hit `/admin/feeds` → "Import / refresh seed CSV" to land the
  +633 sources, then sort by `error_count` to clean up dead URLs.
- Manual: spot-check the lean/reputation ratings for major sources in
  the new batch.
- Roadmap stabilization items remain backlogged: cron job hardening
  (timeouts + flock), PyMySQL connection timeouts, CSRF + auth rate
  limiting. All small, none done.
- v1 limitations still open (sandboxed Python exec, full-text article
  extraction, click→popularity, dedup).

### PRs in this session

- **#7** Fix BUG-006 + roadmap entries (merged)
- **#8** Category tabs (merged)
- **#9** 3-axis feature config (merged)
- **#10** Obscurity features (merged) — required manual DB migration
- **#11** +633 sources + admin auto-deactivate/refresh (merged) —
  requires manual seed CSV re-import

---

## 2026-05-12 — Add `engineering-session-wrapup.md` and `bugs.md`

Two new docs to round out the session-management story:

- `engineering-session-wrapup.md` — checklist the LLM runs at end-of-session
  (or self-triggers when the session is stale/context-polluted). Forces
  updates to history, roadmap, and bugs before stopping.
- `bugs.md` — bug log with statuses `open` / `in-progress` / `attempted` /
  `resolved` / `wontfix`. Pre-populated with the five bugs we hit in the
  v1 deploy (BUG-001 shim, BUG-002 cPanel scaffold, BUG-003 anthropic,
  BUG-004 APPLICATION_ROOT, BUG-005 INSTALL.txt paths).

Updated `new-engineering-session-instructions.md`:
- Step 2 now requires reading `roadmap.md` AND `bugs.md`.
- New step 7: when the user reports a bug, log it in `bugs.md` immediately
  before doing anything else with it.
- New step 11: wrap-up procedure references `engineering-session-wrapup.md`
  and instructs the agent to proactively suggest wrap-up when the session
  is stale.
- Subsequent steps renumbered.

PR: #TBD.

---

## 2026-05-12 — Add `roadmap.md` and wire it into session onboarding

Added `roadmap.md` at the repo root with an initial backlog of ~18 items
spanning `infra`, `new-feature`, `ui`, `backend`, `algo`, `security`, `ops`,
`skunkworks`. Each item is rated Priority (1–10) and LOE (1–10) with a brief
detail block.

Updated `new-engineering-session-instructions.md` to require reading
`roadmap.md` (step 2) and asking the user at session start whether to work
off the roadmap or something else (step 3). Renumbered subsequent steps.

PR: #TBD.

---

## 2026-05-12 — v1 prototype deploy to GoDaddy Web Hosting Plus

### Context

`mhittle/sauce.ai` repo contained a Flask 3 / MySQL / cron-driven news
aggregator built to the original product spec (reproduced at the bottom of this
file). PR #1 landed the initial app, PR #2 cleaned up `INSTALL.txt` for
CI/CD-driven deploys. The cPanel deploy on `sauce.ai/news` had been started
but was hanging — depending on the moment the site returned 404, 500, or never
loaded.

This session: review the repo, diagnose the deploy failures, get the site
running end-to-end, and harden the code/docs against the bugs we hit.

### What v1 ships

- Flask 3 served by cPanel Passenger (LiteSpeed).
- MySQL via PyMySQL, schema at `news/seed/schema.sql`.
- Jinja2 + HTMX + Alpine.js (no build step).
- Cron-driven workers in `news/jobs/`:
  `fetch_feeds.py` (15 min), `classify_pending.py` (5 min),
  `popularity_poll.py` (30 min), `maintenance.py` (nightly).
- Ten per-article ranking features: `political_lean`, `source_lean`,
  `objectivity`, `reading_level`, `info_density`, `journalist_reputation`,
  `source_reputation`, `category`, `country`, `popularity`. Ranking is a
  weighted SQL expression evaluated at query time (no Python per request).
- Classifier: Claude Haiku 4.5 for the two judgment features
  (`political_lean`, `objectivity`); the other eight are deterministic Python
  rules. Degrades to source-level defaults if no API key is configured.
- ~135 seed RSS sources curated in `news/seed/source_lean.csv`.
- Three user views: `/` card feed, `/firehose` live table, `/algo`
  UI/Code/Presets editor.
- Admin under `/admin/*`, gated on `users.is_admin = 1`.

### v1 limitations (deferred to v2, called out in INSTALL.txt §10)

- "Your Algo" Code tab renders the Python equivalent of the user's UI choices
  but does **not execute** user-supplied code. Sandboxed exec is deferred.
- No CSRF tokens beyond same-site cookies, no email verification, no rate
  limiting on auth endpoints.
- Articles store summary + link only; no full-text extraction.
- Internal click signal is recorded but not folded into the popularity score.
- No timeouts/flock on cron scripts (RSS hangs and LLM stalls can pile up).
  Flagged in this session but not fixed.
- PyMySQL connections have no `connect_timeout` / `read_timeout`. Same.

### Deploy bugs hit and fixed

**1. `APPLICATION_ROOT` double-prefix → every URL 404'd**
- `app/__init__.py` wrapped Flask in
  `DispatcherMiddleware({APPLICATION_ROOT: app})` and `app/config.py` defaulted
  `APPLICATION_ROOT=/news`.
- LiteSpeed already mounts the app at `/news` per the cPanel "Application URL"
  setting and strips that prefix before the WSGI request arrives. The
  middleware then saw `PATH_INFO=/`, couldn't match the `/news` mount, and
  returned `NotFound()`.
- Fix: removed `DispatcherMiddleware` and the `APPLICATION_ROOT` default
  entirely. Documented in INSTALL.txt §2b: do NOT set the `APPLICATION_ROOT`
  env var. (PR #3.)

**2. Path mismatch between INSTALL.txt and reality**
- INSTALL.txt §2a said Application root = `sauce.ai/news` (under `~/`).
- But the FTP deploy user `sauce@sauce.ai` is scoped to `~/public_html/sauce.ai/`,
  so CI/CD actually drops files at `~/public_html/sauce.ai/news/`.
- Two Python App entries had been created at different roots; both were trying
  to spawn, both were broken.
- Fix: rewrote INSTALL.txt to use `public_html/sauce.ai/news` consistently.
  (PR #3.)

**3. CloudLinux venv shim resolved `${CWD}` to app root → infinite fork-bomb**
- The shim at `~/virtualenv/public_html/sauce.ai/news/3.11/bin/python` uses
  `CWD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`.
- When LiteSpeed/Passenger invoked it with a bare relative argv[0] (`python`
  from the app-root cwd), `dirname` returned `.`, `cd .` landed in the app
  root, and `${CWD}` became `~/public_html/sauce.ai/news` instead of the venv
  `bin/`.
- `source ${CWD}/activate` etc. all failed; Passenger respawned in a tight
  loop and exhausted the CloudLinux nproc/EP limit, surfacing as
  `fork: Resource temporarily unavailable` everywhere — including the user's
  interactive shell.
- The shim file is `chattr +i`, can't be patched directly without root.
- Fix (workaround): place symlinks in the app root pointing at the real venv
  files. The shim then finds `activate` / `set_env_vars.py` / `python3.11_bin`
  via these symlinks, follows them, and ends up running the right code:
  ```
  cd ~/public_html/sauce.ai/news
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/activate activate
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/set_env_vars.py set_env_vars.py
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/python3.11_bin python3.11_bin
  ```
- The `activate` script (sourced via the symlink) hardcodes `VIRTUAL_ENV` to
  the correct venv path, so the rest of the shim recovers.
- Long-term fix would be a CloudLinux/GoDaddy support ticket — left open.

**4. cPanel overwrote `passenger_wsgi.py` with a self-recursive scaffold**
- When the Python App was created, cPanel scaffolded a default
  `passenger_wsgi.py` containing:
  ```python
  wsgi = imp.load_source('wsgi', 'passenger_wsgi.py')
  ```
- That loads `passenger_wsgi.py` from within `passenger_wsgi.py` — infinite
  recursion → `RecursionError` at module load. Python crashed too fast to
  flush stderr → Passenger reported "exited prematurely" with no app output.
- Fix: manually overwrote the file on the server with the repo's real
  content (`from app import create_app; application = create_app()`).
- Risk: cPanel may re-scaffold on certain operations. Backup of the working
  version lives at `~/passenger_wsgi.py.working` on the server.

**5. `anthropic==0.39.0` incompatible with `httpx>=0.28`**
- Fresh `pip install -r requirements.txt` resolved an httpx that no longer
  accepts the `proxies=` keyword. `anthropic==0.39.0` passes that keyword to
  `httpx.Client.__init__` → `TypeError`.
- Fix: bumped to `anthropic==0.101.0`. (PR #4.) The API surface this codebase
  uses (`messages.create(...)`, `system=[{cache_control: ephemeral}]`,
  `usage.*`) is unchanged.

### Code changes shipped this session

- `app/__init__.py` — dropped `DispatcherMiddleware` and the `APP_ROOT`
  context variable.
- `app/config.py` — dropped `APPLICATION_ROOT` and `SESSION_COOKIE_PATH`.
- `jobs/_bootstrap.py` — `setup_logging` falls back to stderr-only if `logs/`
  is unwritable; doesn't re-init `basicConfig` on repeat calls.
- `jobs/fetch_feeds.py`, `classify_pending.py`, `popularity_poll.py`,
  `maintenance.py` — each starts with
  `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` so the
  scripts work regardless of cron's cwd.
- `jobs/_selftest.py` — new diagnostic. Prints Python info, env-var
  visibility, MySQL connectivity. Cron failures stop being silent.
- `INSTALL.txt` — rewritten for the actual deploy path
  (`public_html/sauce.ai/news`); cron commands now `source activate` and
  redirect output to `logs/cron.log` (not `/dev/null`); §8 troubleshooting
  covers every failure mode hit this session; §9 adds secrets-hygiene.
- `requirements.txt` — `anthropic==0.101.0` (was `0.39.0`).

### Server-side state (not in repo, load-bearing)

- Three symlinks in `~/public_html/sauce.ai/news/`: `activate`,
  `set_env_vars.py`, `python3.11_bin` → see bug 3 above.
- `~/passenger_wsgi.py.working` — backup of the corrected wsgi file (bug 4).
- `~/htaccess.working` — backup of the env-vars `.htaccess`.
- `~/news-db-YYYYMMDD.sql` — DB snapshot taken after first successful run.
- cPanel env vars saved on the Python App (canonical source of truth for
  secrets — not in the repo, not in `.env`).

### What's running as of session end

- Python App: 3.11.14, Application root `public_html/sauce.ai/news`,
  URL `sauce.ai/news`, startup `passenger_wsgi.py`, entry `application`.
- DB: `lt1ih6uyy2z6_news` populated with schema + seed sources.
- Cron: four jobs scheduled (15min / 5min / 30min / nightly).
- Site live at https://sauce.ai/news.

### Security notes from this session

- The Anthropic API key and DB password were pasted into the live chat
  transcript earlier in the session. Both were rotated before close.
- The `.htaccess` env-var file is sensitive even though it's not committed.

### PRs in this session

- **#3** — Fix install bugs surfaced on first GoDaddy deploy (merged).
- **#4** — Bump anthropic SDK to 0.101.0 + add these two engineering docs
  (draft; ready to merge).

---
