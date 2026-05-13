# sauce.ai/news — Bug log

User-reported bugs (and a few internally-discovered ones worth tracking).
**Reviewed and updated at the end of every session** per
`engineering-session-wrapup.md`. When the user reports a bug mid-session,
add an entry here with status `open` before doing anything else.

## Conventions

Each bug gets a sequential ID (`BUG-001`, `BUG-002`, …) and a status:

- `open` — reported, not yet investigated or fixed
- `in-progress` — actively being worked
- `attempted` — fix was tried but didn't fully resolve; workaround may be
  in place; root cause still outstanding
- `resolved` — fixed and verified
- `wontfix` — explicitly closed without a fix (rare; document rationale)

Each entry includes: title, status, reporter, date opened, description,
repro (if known), and fix notes / PR# (if any).

Sort with `open` and `in-progress` at the top, then `attempted`, then
`resolved` (most recent first). `wontfix` at the bottom.

---

## Open

### BUG-009 — `classify_pending` dies on every tick with `MySQL server has gone away`
**Status:** in-progress · **Reporter:** internal · **Opened:** 2026-05-13

Cron stopped producing log output on prod at 2026-05-12 22:50 server-local.
Every prior `classify_pending` invocation back to ~22:30 ends in the same
traceback: PyMySQL `OperationalError (2006, "MySQL server has gone away
(ConnectionResetError(104, 'Connection reset by peer'))")` on the first
`INSERT INTO article_features` of the write block. Reproducible on demand
by running `python jobs/classify_pending.py` from an SSH session.

**Root cause:** `_run()` opens one PyMySQL connection at the top, then
each batch iteration spends 30–200 s on:
1. `classify_batch_llm` HTTP POST to Anthropic (1–30 s),
2. `detect_paywall` sequential HTTP per article (5–60 s for batch of 10),
3. `extract_body` sequential HTTP per article (10–100 s for batch of 10).

Shared-host MySQL on GoDaddy enforces a short `wait_timeout` and closes
idle sockets aggressively. By the time we get to the writes the kernel
RSTs us. Same idle-gap pattern exists in `popularity_poll` (all Reddit/HN
HTTP happens before any writes) and to a lesser degree `fetch_feeds`
(one HTTP GET before each source's writes).

**Confirms BUG-008 hypothesis #3** — `classify_pending` was wallclock-
starved, not by the budget, but by repeatedly crashing mid-batch and
leaving thousands of rows in `status='pending'`. Once writes failed the
script aborted, articles never advanced, and the feed went stale.

**Fix:** call `conn.ping(reconnect=True)` at every point the connection
has been idle long enough to plausibly have been killed — top of each
`classify_pending` loop iteration, right before its write block,
before `popularity_poll` writes, and at the start of every `fetch_feeds`
`fetch_one`. PyMySQL re-establishes the socket transparently when needed
and is a no-op when the connection is alive. Branch
`claude/onboard-news-aggregator-y9qWK`.

**Repro:** see prod log `~/public_html/sauce.ai/news/logs/cron.log`, last
80 lines as of 2026-05-12 22:50 — every traceback ends at
`classify_pending.py:230` `cur.execute(...)` of `INSERT INTO article_features`.

---

### BUG-008 — Feed feels stale; not enough fresh content / new articles
**Status:** open · **Reporter:** user · **Opened:** 2026-05-13

User reports `/` feed "feels stale already" — not seeing enough fresh
content or new articles surfacing between visits.

**Hypotheses to investigate (in order of likelihood):**
1. `fetch_feeds` cron not actually ticking on prod (job_lock leftover,
   cron entry malformed, venv shim regression).
2. Large portion of the +633 source import (PR #11) is dead and
   auto-deactivated at `error_count >= 10`, shrinking the active pool
   below what the feed needs.
3. `classify_pending` is wallclock-budget-starved (paywall HTTP +
   trafilatura extraction + LLM all share `CLASSIFY_BUDGET_SECONDS`),
   so newly-fetched rows sit in `status='pending'` and never reach the
   feed.
4. Dedup `WHERE a.story_id IS NULL OR a.id = a.story_id` (PR #24) is
   collapsing too many cards into one canonical per cluster.
5. Feed query has too tight a recency window or the ranking is
   penalizing freshness.
6. Per-user `user_source_prefs` hide/downweight rows from earlier
   thumbs-down prompts are shrinking the visible pool.

**Repro:** load `/` while signed in (and signed out for comparison),
note whether top cards differ from the prior visit.

**Next steps:** check `/admin/feeds` for active source count + recent
fetch timestamps, `/admin/articles` (if it exists) for status
breakdown, then add diagnostic SQL counts to the investigation.

---

## In progress

(none currently)

---

## Attempted (root cause not fully fixed; workaround in place)

### BUG-001 — CloudLinux venv shim resolves `${CWD}` to app root, fork-bombs Passenger
**Status:** attempted · **Reporter:** internal · **Opened:** 2026-05-12

The shim at `~/virtualenv/.../bin/python` computes
`CWD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`. When LiteSpeed/Passenger
invokes it with a relative argv[0] (`python` from app-root cwd), `${CWD}`
resolves to `~/public_html/sauce.ai/news` instead of the venv `bin/`. Every
spawn fails, Passenger respawns in a tight loop, CloudLinux nproc limit
exhausts in seconds.

**Repro:** create a Python App on this account, invoke `python --version`
with the venv on PATH from the app-root cwd; the shim prints
`No such file or directory` for `activate`, `set_env_vars.py`,
`python3.11_bin`.

**Workaround in place:** three symlinks in the app root point at the real
venv files. The shim follows them and recovers. See `engineering-history.md`
2026-05-12 entry, bug 3. The shim itself is `chattr +i` and can't be patched
without root.

**Root-cause fix:** would require CloudLinux/GoDaddy to update the shim to
resolve `BASH_SOURCE[0]` robustly. Pending a support ticket — see
`roadmap.md` "CloudLinux/GoDaddy support ticket re: shim" (Pri 5, LOE 1).

### BUG-002 — cPanel overwrites `passenger_wsgi.py` with self-recursive scaffold
**Status:** attempted · **Reporter:** internal · **Opened:** 2026-05-12

On Python App creation (and possibly on certain edits), cPanel scaffolds a
default `passenger_wsgi.py` containing
`wsgi = imp.load_source('wsgi', 'passenger_wsgi.py')`. This loads
`passenger_wsgi.py` from within `passenger_wsgi.py` — infinite recursion →
`RecursionError` at module load → Passenger reports "exited prematurely"
with no app output (Python crashes too fast to flush stderr).

**Repro:** delete or rename the current `passenger_wsgi.py` on the server,
recreate the Python App in cPanel, check the file contents.

**Workaround in place:** the correct file is in the repo and gets restored
on FTP deploy. A backup also lives at `~/passenger_wsgi.py.working` on the
server for fast manual recovery. Documented in `INSTALL.txt` §8A.

**Root-cause fix:** none we control — cPanel's scaffold behavior is part of
the platform. Mitigation is "know it can happen and have the backup ready".

---

## Resolved

### BUG-007 — Site returns 500 after rapid PR push (pending migrations)
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-13 · **Closed:** 2026-05-13

After merging ~20 PRs in succession without testing between them,
`sauce.ai/news` started returning 500 on every request. Two outstanding
prod migrations from `manual-actions.md` Open section were the cause:

- `sources.owner_id` (PR #29) — `feed.py:65` and `firehose.py:49`
  reference `s.owner_id` in the visibility WHERE clause on every page
  load (anon path included), so a missing column alone 500'd every
  reader route.
- `user_signals` + `user_source_prefs` (PR #19) — `feed.py` LEFT JOINs
  `user_source_prefs` for signed-in users; would also have 500'd
  signed-in feed loads.

**Fix:** ran both migrations in phpMyAdmin against `lt1ih6uyy2z6_news`,
restarted the Python App from cPanel. Site recovered. Both manual-action
entries moved to Completed.

**Process learning:** merging code that references a not-yet-applied
migration is a guaranteed prod break. The `manual-actions.md` tracker
PR (#22) was created exactly for this and the lifecycle hook was
followed — the entries were logged when the PRs landed. The gap was
that the migrations didn't get *run* between merges. For high-PR
sessions, run the migrations before each merge (or batch them and
restart once at the end) instead of letting the queue grow.

### BUG-006 — Article links in feed do nothing on click
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-12 · **Closed:** 2026-05-12

`feed_cards.html` had `hx-post` directly on the article `<a>` tags for
click-tracking. HTMX intercepts the click and calls `preventDefault()` on
anchors with `hx-*` attributes, so the tracking POST fired but the browser
never navigated to the article URL.

**Fix:** replaced `hx-post` on the two anchors (thumbnail + title) with
`onclick="fetch('/news/click/<id>', {method:'POST', keepalive:true})"`. The
browser now follows `href` normally and the tracking request uses
`keepalive: true` so it survives the page transition. The firehose template
already used plain anchors (no `hx-post`) so no change needed there.

### BUG-003 — `anthropic==0.39.0` crashes on fresh install with httpx>=0.28
**Status:** resolved · **Reporter:** internal · **Opened:** 2026-05-12 · **Closed:** 2026-05-12 (PR #4)

`anthropic==0.39.0` passes `proxies=` to `httpx.Client.__init__()`. `httpx`
removed that keyword in 0.28. Fresh `pip install -r requirements.txt`
resolves a newer httpx and `from anthropic import Anthropic; Anthropic(...)`
raises `TypeError: Client.__init__() got an unexpected keyword argument
'proxies'`.

**Fix:** bumped `anthropic` to `0.101.0` in `requirements.txt`. API surface
we use is unchanged. PR #4.

### BUG-004 — `APPLICATION_ROOT` double-prefix 404'd every URL
**Status:** resolved · **Reporter:** internal · **Opened:** 2026-05-12 · **Closed:** 2026-05-12 (PR #3)

`app/__init__.py` wrapped the WSGI app in `DispatcherMiddleware({/news: app})`
and `config.py` defaulted `APPLICATION_ROOT=/news`. LiteSpeed already mounts
the app at `/news` and strips the prefix before the WSGI request — the
middleware then saw `PATH_INFO=/` and returned `NotFound()` because the
mount was at `/news`.

**Fix:** removed `DispatcherMiddleware` and `APPLICATION_ROOT` defaults
entirely. INSTALL.txt §2b now documents: do NOT set `APPLICATION_ROOT` in
cPanel env vars. PR #3.

### BUG-005 — `INSTALL.txt` paths pointed at non-existent directory
**Status:** resolved · **Reporter:** internal · **Opened:** 2026-05-12 · **Closed:** 2026-05-12 (PR #3)

INSTALL.txt §2a said Application root = `sauce.ai/news` (i.e. `~/sauce.ai/news`).
But the FTP user `sauce@sauce.ai` is scoped to `~/public_html/sauce.ai/`,
so CI/CD actually drops files at `~/public_html/sauce.ai/news/`. Result:
Python App pointed at a directory that didn't exist, plus dual Python App
entries from earlier attempts at the wrong root.

**Fix:** rewrote `INSTALL.txt` to use `public_html/sauce.ai/news`
consistently. PR #3.

---

## Won't fix

(none currently)
