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
`trending_topic_articles` tables (PR #71, /trending page). A DB
rebuild from `seed/schema.sql` already includes these.

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

- **PR #70** — Full-text article search (draft). Branch
  `claude/onboard-news-aggregator-j0JdN`.

### Open items

- Maintainer: apply the FULLTEXT migration before merge, then click
  through `/search` (nav box → results → Load more) and confirm
  muted-source/visibility scoping.
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

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-17

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
