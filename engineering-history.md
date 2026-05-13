# sauce.ai/news — Engineering history

Chronological log of architecture decisions, bugs hit, and fixes applied to
sauce.ai/news. **Read end-to-end before making changes.** Append a new dated
section whenever something meaningful happens — see
`new-engineering-session-instructions.md` for what counts as "meaningful".

---

## 2026-05-13 — Thumbs up/down on cards + signal foundation (PR #TBD)

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

- **#TBD** Thumbs up/down on cards + signal foundation (draft)

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
