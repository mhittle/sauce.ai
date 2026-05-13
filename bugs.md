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

(none currently)

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

### BUG-011 — Feed shows same articles on page reload; doesn't refresh by recency
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-13 · **Closed:** 2026-05-13

User reported that loading `/` kept showing yesterday's articles even
after reloading. Pipeline was healthy (BUG-009's reconnect fix had
caught up the pending backlog); the issue was in `app/ranking.py`.

**Root cause:** ranking was purely additive. Quality features
(`objectivity`, `info_density`, `source_reputation`, etc.) summed to
~3.0 for a great article; recency was just one more additive term
`recency_w * EXP(-hours/24)` capped at `recency_w` (0.7 in the default
`balanced` preset). A 3-day-old high-quality article scored ~3.0 + 0.04
≈ 3.04; a 1-hour-old medium-quality article scored ~1.5 + 0.7 ≈ 2.2.
Static quality dominated forever; reloads returned the same top-30
because the underlying score barely changed minute to minute.

**Fix:** changed `recency` semantics from additive term to
**multiplicative freshness gate**: `score = quality * EXP(-recency_w *
hours / 24)`. The `recency` slider now controls decay strength rather
than a small additive contribution. With the default `recency=0.7`,
the multiplier is 1.0 at 0h, ~0.50 at 24h, ~0.25 at 48h, ~0.05 at 4d,
~0.007 at 7d — a 4-day-old article is structurally crushed regardless
of its static quality, while fresh quality articles still rank above
fresh mediocre ones. `recency=0` opts out (legacy behavior).
`weights_to_expression` updated so the `/algo` Code tab matches.

**Side note:** `feed.py:93` keeps the 7-day window. With the
multiplicative decay it's effectively self-narrowing — no need to
tighten it.

**Note on numbering:** originally logged as BUG-010 in this session;
renumbered to BUG-011 on rebase because a parallel session's PR #35
landed BUG-010 first (feature bars on cards).

### BUG-010 — Per-feature ranking bars on cards don't reflect feature values
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-13 · **Closed:** 2026-05-13

Every feed card's "feature-bars" graphic rendered identically regardless
of the article's `objectivity / info_density / reading_level /
source_reputation / popularity` values.

**Root cause:** mismatch between the template and the CSS. The template
in `app/templates/partials/feed_cards.html` set the bar value via inline
`style="width: NN%"`, but `app/static/style.css:99` declares
`.feature-bars i { flex: 1 }` which makes the `<i>` a flex child whose
width is controlled by `flex-grow`, not `width` — so the inline width
was ignored. The neighboring CSS rule at line 100 drives the visible
fill with a `linear-gradient(... var(--w, 50%), ...)` and falls back to
`50%` whenever `--w` is unset, which is what every card was rendering.

**Fix:** changed the template to set `style="--w: NN%"` (matching the
custom-property the gradient reads). Also enriched the `title` tooltip
to include the numeric value (`Objectivity 0.87`) since the bars are
small and a hover readout costs nothing.

No DB change, no migration. The fix is a template/CSS-contract
correction and is picked up on the next FTP deploy + Python App
restart (Jinja autoreloads templates, but a restart is cleaner).

### BUG-009 — `classify_pending` died on every tick with `MySQL server has gone away`
**Status:** resolved · **Reporter:** internal · **Opened:** 2026-05-13 · **Closed:** 2026-05-13 (PR #32)

Cron stopped producing log output on prod at 2026-05-12 22:50 server-local.
Every `classify_pending` invocation back to ~22:30 ended in the same
traceback: PyMySQL `OperationalError (2006, "MySQL server has gone away
(ConnectionResetError(104, 'Connection reset by peer'))")` on the first
`INSERT INTO article_features` of the write block.

**Root cause:** `_run()` opened one PyMySQL connection at the top of the
script, then each batch iteration spent 30–200 s on (1) the Anthropic LLM
HTTP POST, (2) sequential `detect_paywall` HTTP for the 10-article batch,
(3) sequential `extract_body` HTTP for the 10-article batch — all while
the MySQL socket sat idle. GoDaddy shared MySQL closes idle sockets
aggressively (short `wait_timeout`); the kernel RSTs the connection and
the next `cur.execute` blows up. Same idle-gap pattern existed in
`popularity_poll` (all Reddit/HN HTTP before any writes) and to a lesser
degree `fetch_feeds` (one HTTP GET before each source's writes).

**Fix (PR #32):** `conn.ping(reconnect=True)` at every plausible idle
point — top of each `classify_pending` batch iteration, right before its
write block, before `popularity_poll` writes, and at the start of every
`fetch_feeds.fetch_one`. PyMySQL transparently re-establishes the
connection (preserving autocommit) when the server has killed it, no-op
when alive. Verified on prod via manual tick: `classified=10
llm_articles=10 cost_usd=0.0037` — first successful tick after ~30
minutes of crashes. Confirmed BUG-008 hypothesis #3.

### BUG-008 — Feed feels stale; not enough fresh content / new articles
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-13 · **Closed:** 2026-05-13 (PR #32)

**Root cause:** classify_pending was crashing mid-batch on every cron
tick (see BUG-009), leaving ~7700 rows stuck in `status='pending'` so
they never reached the feed. Once the reconnect was fixed and the
backlog drained, freshness returned.

**Fix (PR #32):** see BUG-009 reconnect fix. Plus same PR parallelized
the per-article HTTP work in `classify_pending` (paywall + body
extraction) via two `ThreadPoolExecutor(max_workers=10)` fan-outs and
bumped `CLASSIFY_BUDGET_SECONDS` default from 90→240, taking per-tick
throughput from ~10 articles to **180/tick** (verified on prod). The
backlog drains in ~3 hours instead of ~60 at the old serial rate.

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
