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
`maintenance` nightly 03:30 UTC · `send_digest` 12:00 UTC ·
`discover_harvest` hourly :15 · `discover_promote` 04:00 UTC ·
`discover_llm` Mon 05:00 UTC. Each line `source`s the venv `activate`
and appends to `logs/cron.log`; all wrapped in `job_lock` (fcntl) so an
overlapping tick no-ops.

---

## 2026-05-17 — Multiple saved algorithm profiles (user-empowerment cluster, Theme A)

### Context

Roadmap "Multiple saved algorithms / profiles" (Pri 7, LOE 4) — the
structural keystone of the user-empowerment cluster (Shareable gallery,
A/B split, Onboarding all lean on it). Picked by the user this session.

### What shipped (PR draft)

- **No DB migration.** `user_algorithms` already has `name` +
  `is_active` + `idx_ua_user(user_id, is_active)`; the work is purely
  app logic. Every existing consumer (`feed.py`, `firehose.py`,
  `send_digest.py`, `algo.py`) already selects
  `WHERE is_active = 1 ... LIMIT 1`, so the only invariant to preserve
  is **exactly one active row per user** — kept by an atomic
  clear-all-then-set activate.
- **`app/profiles.py`** (new, Flask-free, DB-free): `clean_profile_name`
  (trim, 120-char cap matching the column, fallback), `next_default_name`
  ("Custom", "Custom 2", … case/space-insensitive), `pick_promotion`
  (which profile becomes active when the active one is deleted).
- **`app/routes/algo.py`**: `_list_profiles`, atomic ownership-checked
  `_activate`; `_render_editor` passes `profiles`. New routes:
  `POST /algo/profiles/new` (saves current editor sliders as a new
  active profile; HX returns 204 + `HX-Redirect` so the bar refreshes),
  `POST /algo/profiles/[<id>/]activate` (path **or** form `aid`;
  `next=feed` redirects back to `/`), `POST /algo/profiles/<id>/rename`,
  `POST /algo/profiles/<id>/delete` (refuses the last one; promotes a
  replacement if the active one is deleted). `save` / `use_preset` /
  `describe` / `onboarding` unchanged — they still act on the active row.
- **`algo.html`**: a profile-management bar (per-profile Use / inline
  Rename / Delete + active badge) and a "Save as new profile" name
  input next to "Save algorithm".
- **`feed.py` / `feed.html`**: the full-page feed render loads the
  user's profiles and renders an "Algorithm:" `<select>` switcher in
  `.feed-controls` (shown only when signed-in with ≥2 profiles); posts
  to the no-arg `profile_activate` with `next=feed`.
- **`style.css`**: appended a `.profile-bar` / `.profile-switch` block.
- **`tests/test_algo_profiles.py`**: 12 cases for the pure helpers
  (anthropic/pymysql-free, sandbox-runnable). `pytest` local sandbox:
  the 12 new pass; full collectible run 125 passed / 13 failed / 12
  collection-errors — **all failures + errors are the known
  environmental `ModuleNotFoundError` (no requests/pymysql/cryptography/
  dotenv)**, none in profiles/algo/feed. Templates Jinja-parse clean;
  changed `.py` `py_compile` clean.

### Known follow-ups (not in scope this PR)

- `use_preset` still overwrites the *active* profile's name+weights
  with the preset (pre-existing behavior; mildly surprising once you
  have named profiles). A "create preset as new profile" option is the
  natural next polish.
- Live Flask route + in-browser UX not verifiable in this sandbox
  (`app.db`→pymysql); needs maintainer/CI exercise.

### CSRF interplay (PR #58)

Rebased on top of PR #58 (CSRF + auth rate limiting), which landed on
`main` during this session. All four new plain POST forms (profile
Use / Rename / Delete on `/algo`, switcher on `/`) carry
`{{ csrf_field() }}`. "Save as new profile" is an `hx-post` button,
covered automatically by `base.html`'s global `htmx:configRequest`
`X-CSRF-Token` hook. No new CSRF-exempt endpoints (only
`account.unsubscribe` stays exempt, unchanged).

### Server-side state touched

None. No DB migration, no cron, no env-var, no symlink, no pip dep.
Standard Python App restart on deploy so the new routes/templates load.

### PR

- **PR (draft)** — Multiple saved algorithm profiles. Branch
  `claude/onboard-news-aggregator-420r6`, rebased on `origin/main`
  (`5c576e9`, includes PR #58 CSRF). roadmap.md / algo.html / feed.html
  union-resolved cleanly; engineering-history.md ours-first.

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

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-17

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
