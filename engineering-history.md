# sauce.ai/news — Engineering history

Chronological log of architecture decisions, bugs hit, and fixes applied to
sauce.ai/news. **Read end-to-end before making changes.** Append a new dated
section whenever something meaningful happens — see
`new-engineering-session-instructions.md` for what counts as "meaningful".

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
