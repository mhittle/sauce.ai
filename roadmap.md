# sauce.ai/news — Roadmap

Backlog of future sprints, features, and projects. **At the start of every
engineering session, ask the user whether to work off this roadmap or
something else** (per `new-engineering-session-instructions.md`).

## Conventions

Each item is rated on three axes:

- **Priority** (1–10): how much this matters. 10 = drop-everything, 1 = nice to have someday.
- **LOE** (1–10): rough effort estimate. 1 = under an hour, 10 = multi-week project.
- **Category**: one or more of `infra`, `new-feature`, `ui`, `backend`, `algo`, `security`, `ops`, `skunkworks`, `docs`. Add new categories as needed; document them here.

Status values: `backlog` (default), `in-progress`, `done`, `dropped`.

Add new items at the bottom of the appropriate section. When you move an item
to `done`, also append a section to `engineering-history.md` describing what
shipped.

---

## At-a-glance

| Pri | LOE | Category | Title | Status |
| --- | --- | --- | --- | --- |
| 9 | 8 | backend, new-feature | Sandboxed Python algorithm execution | backlog |
| 7 | 4 | algo, new-feature | Paywall feature (per-article detection) | in-progress |
| 8 | 7 | algo, backend | Article deduplication across sources | backlog |
| 8 | 3 | infra | Cron job hardening: timeouts + flock | backlog |
| 8 | 2 | backend | PyMySQL connection timeouts | backlog |
| 7 | 4 | security | CSRF tokens + auth rate limiting | backlog |
| 7 | 4 | algo | Fold internal clicks into popularity | backlog |
| 7 | 4 | ui | Mobile / responsive polish | backlog |
| 6 | 5 | backend, new-feature | Full-text article extraction | backlog |
| 6 | 4 | new-feature, ui | Article save / bookmark | backlog |
| 6 | 4 | new-feature, ui | User-added RSS feed subscriptions | backlog |
| 6 | 6 | new-feature, ui | Search across articles | backlog |
| 6 | 7 | new-feature, infra | Daily personalized email digest | backlog |
| 5 | 5 | new-feature, algo | Trending topics view | backlog |
| 5 | 5 | infra | Test coverage expansion | backlog |
| 5 | 3 | security | Email verification on signup | backlog |
| 5 | 1 | ops | CloudLinux/GoDaddy support ticket re: shim | backlog |
| 4 | 7 | infra, skunkworks | Migrate to VPS (gunicorn + nginx) | backlog |
| 3 | 2 | ui | Dark mode | backlog |

---

## Items in detail

### Paywall feature (per-article detection)
**Priority:** 7 · **LOE:** 4 · **Category:** algo, new-feature · **Status:** in-progress

Add a `paywall` feature to the ranking catalog so users can down-weight or
hard-filter articles behind subscription walls.

v1 detection is active per-article: during `classify_pending`, GET the
article URL with an 8s timeout and look for paywall signals — JSON-LD
`isAccessibleForFree: false`, `<meta property="article:content_tier">`
locked/paid/metered, and a small set of paywall phrases on short bodies.
Sites that block (timeout, 4xx) score 0.5 (suspected) per product
direction. Stored in `article_features.paywall` as 0..1.

Catalog entry is unsigned, default direction 0.0 (prefer free), default
weight 0.0 (opt-in — existing user algos unchanged). Threshold off by
default; set ~0.2 to hide anything but free articles.

Follow-ups: per-source override in admin if active detection is
unreliable for a given outlet; signed-in-browser reader heuristic for
soft paywalls.

### Sandboxed Python algorithm execution
**Priority:** 9 · **LOE:** 8 · **Category:** backend, new-feature · **Status:** backlog

The original spec called for users to write their own ranking algorithms in
Python. v1 ships the "Code" tab on `/algo` as read-only — it renders the
Python equivalent of the UI-chosen weights but doesn't execute user-supplied
code. This is the single biggest feature gap vs the spec.

Approach: needs a sandbox (RestrictedPython, subprocess + seccomp, or
WebAssembly). Must enforce CPU/memory/wallclock limits. User code receives a
fixed input shape (article features) and returns a score. Result is used at
query time the same way the SQL expression is today.

Open questions:
- Sandbox choice. RestrictedPython is easiest to integrate but porous;
  subprocess + resource limits is safer but slower.
- How to handle errors in user code (default back to weighted SQL? show
  warning in UI?).
- Caching of computed scores to avoid running user code per article per
  request.

### Article deduplication across sources
**Priority:** 8 · **LOE:** 7 · **Category:** algo, backend · **Status:** backlog

A single story (e.g. an AP wire) often gets republished by dozens of
sources. The firehose and feed both currently show all copies, which is
noisy.

Approach: probably embedding-based similarity (Claude or sentence-transformer)
clustered into "story groups". Each `articles` row gets a `story_id` and the
feed dedupes by story_id, showing the canonical (highest-source-reputation)
copy with a "N other sources" affordance.

Cost concern: embedding every article through Claude adds non-trivial
spend. Cheaper alternatives: TF-IDF on titles + first-paragraph for a coarse
first pass, only embed near-matches.

### Cron job hardening: timeouts + flock
**Priority:** 8 · **LOE:** 3 · **Category:** infra · **Status:** backlog

The cron scripts have no mutex (a slow `fetch_feeds` run can be re-launched
on top of itself when the 15-min cron fires again) and weak/no per-request
timeouts on RSS fetches and the Claude API call. On shared hosting this can
chew through the nproc/EP limit. Flagged in `engineering-history.md` §2026-05-12.

Tasks:
- Wrap each cron `main()` in an `fcntl.flock` on a per-job lockfile in `news/logs/`. Exit early if held.
- `jobs/fetch_feeds.py`: fetch with `requests.get(url, timeout=(5, 15))`, hand bytes to `feedparser.parse()`. Drop the `socket.setdefaulttimeout(20)` line.
- `app/classifier/llm.py`: pass `timeout=30.0` to `client.messages.create(...)`.
- `jobs/popularity_poll.py`: shared `requests.Session`, wallclock budget on the HN item loop.
- Lower `FEED_FETCH_BATCH` from 80 to ~20 until the loop is proven snappy.

### PyMySQL connection timeouts
**Priority:** 8 · **LOE:** 2 · **Category:** backend · **Status:** backlog

`app/db.py` builds the connection with no `connect_timeout` / `read_timeout`
/ `write_timeout`. If MySQL is slow or wedged, the web request hangs
forever, holding a Passenger worker → quickly exhausts the cPanel process
budget. Tiny fix; high-leverage.

Add `connect_timeout=5, read_timeout=15, write_timeout=10` to both
`pymysql.connect(...)` callsites.

### CSRF tokens + auth rate limiting
**Priority:** 7 · **LOE:** 4 · **Category:** security · **Status:** backlog

v1 relies on same-site cookies only. Acceptable for a closed prototype, not
for anything public. Add Flask-WTF (or hand-rolled) CSRF on POST routes,
and a simple sliding-window rate limit on `/auth/login`, `/auth/signup`.

### Fold internal clicks into popularity
**Priority:** 7 · **LOE:** 4 · **Category:** algo · **Status:** backlog

`user_clicks` is being recorded but isn't used in the ranking. Popularity
today is only Reddit + HN. Internal clicks are a stronger signal for our
users — fold them in.

Approach: per-article click-rate (clicks per impression over rolling 24h)
normalized to 0..1, max'd with the external signal so unpopular-on-Reddit-but-
popular-here articles still rank.

### Mobile / responsive polish
**Priority:** 7 · **LOE:** 4 · **Category:** ui · **Status:** backlog

The card grid wraps OK on phone widths but the algo editor is a mess, the
firehose table is a horror, and tap targets are small. Audit each page on
375px width, fix.

### Full-text article extraction
**Priority:** 6 · **LOE:** 5 · **Category:** backend, new-feature · **Status:** backlog

Today the app stores `summary` + `link` only. Full text would enable better
classification (Flesch-Kincaid is much more accurate on body text than RSS
summaries), better dedup (title-only is brittle), and an on-site reader
view that keeps users out of paywalls/redirects.

Cheap path: `trafilatura` or `readability-lxml` invoked after fetch.
Storage: a new `article_body` column or table to avoid bloating the main
row.

### Article save / bookmark
**Priority:** 6 · **LOE:** 4 · **Category:** new-feature, ui · **Status:** backlog

Star/bookmark button on each card, "Saved" view in the nav. Per-user list.
Pure CRUD on a new `user_saves` table. Good first-feature for re-engagement.

### User-added RSS feed subscriptions
**Priority:** 6 · **LOE:** 4 · **Category:** new-feature, ui · **Status:** backlog

Let users paste an RSS URL and add it to their personal feed list. UI on
`/algo` or a new `/sources` page. Server-side: validate the URL is a real
feed before saving, then include user-added sources in `fetch_feeds`.
Per-user filtering already exists via the algo weights; this just expands
the source pool a given user pulls from.

### Search across articles
**Priority:** 6 · **LOE:** 6 · **Category:** new-feature, ui · **Status:** backlog

Full-text search box in the nav, results page sorted by relevance + recency.
MySQL FULLTEXT index works for v1; revisit if quality is poor (then SQLite
FTS5 in-process, or Meilisearch on a VPS).

### Daily personalized email digest
**Priority:** 6 · **LOE:** 7 · **Category:** new-feature, infra · **Status:** backlog

Once a day, send each user a 5–10 article digest ranked by their algorithm.
Requires: outbound email (cPanel's SMTP works), digest template, opt-in
toggle in settings, an unsubscribe link, and a new cron job. Watch
deliverability — shared cPanel IPs are reputation-mixed.

### Trending topics view
**Priority:** 5 · **LOE:** 5 · **Category:** new-feature, algo · **Status:** backlog

After dedup exists, a "Trending" page that groups today's stories by
entity/topic with a count of sources covering each. Topic extraction can
piggyback on the existing classifier batch (cheap addition to the LLM
call).

### Test coverage expansion
**Priority:** 5 · **LOE:** 5 · **Category:** infra · **Status:** backlog

20 tests today, mostly classifier rules and ranking. No tests for routes,
auth, admin pages, or cron pipeline end-to-end. Add Flask test-client
coverage for the top-level routes and a SQLite-backed integration test for
the classify pipeline.

### Email verification on signup
**Priority:** 5 · **LOE:** 3 · **Category:** security · **Status:** backlog

Confirmation email on signup, gate is_active until clicked. Easy once the
email infra for the digest exists, so probably do it alongside.

### CloudLinux/GoDaddy support ticket re: shim
**Priority:** 5 · **LOE:** 1 · **Category:** ops · **Status:** backlog

The venv shim's `BASH_SOURCE[0]` resolution fails when Passenger invokes
with a relative argv[0]. Three load-bearing symlinks (`activate`,
`set_env_vars.py`, `python3.11_bin`) in the app root work around it. File
a ticket asking CloudLinux/GoDaddy to fix the shim so we can remove the
workaround.

### Migrate to VPS (gunicorn + nginx)
**Priority:** 4 · **LOE:** 7 · **Category:** infra, skunkworks · **Status:** backlog

GoDaddy shared cPanel is a constant fight: nproc limits, hostile cPanel
scaffolds, immutable venv shims, fork-bombs on respawn. A $6–10/month VPS
(Hetzner, Linode, DO) removes 90% of the failure modes. Code transfers
cleanly: Flask + gunicorn behind nginx, MySQL local, system cron.

Defer until shared hosting actively breaks something the customer notices.

### Dark mode
**Priority:** 3 · **LOE:** 2 · **Category:** ui · **Status:** backlog

Toggle in the user nav. CSS custom-property swap. Persist preference in
`localStorage`.

---

## Done

Reverse chronological. Each entry links to the merged PR; the matching
narrative lives in `engineering-history.md` under the same date.

### 2026-05-12

- **Editorial serif wordmark in topnav** — ad-hoc, ui. PR #13. Subtle
  typographic personality: `sauce.ai` in system serif, `news` in italic.
- **3-axis feature config (Direction + Weight + Threshold)** — Pri 8, LOE 7,
  ui/backend/algo. PR #9.
- **Expand source catalog to ~635 sources** (shipped at 768) — Pri 8, LOE 5,
  ops/new-feature. PR #11. Includes auto-deactivate of dead feeds at
  error_count=10 + Refresh button in `/admin/feeds`.
- **Obscurity features (story + source)** — Pri 7, LOE 6, algo/new-feature.
  PR #10. Requires manual DB migration on existing installs
  (`seed/migrations/2026-05-12-obscurity.sql`).
- **Category tabs on `/` feed** — Pri 7, LOE 3, ui/new-feature. PR #8.
- **BUG-006 — article links don't open on click** (filed in `bugs.md`). PR #7.

### Earlier

- **Session-management doc framework** — `engineering-history.md`,
  `roadmap.md`, `bugs.md`, `engineering-session-wrapup.md`,
  `new-engineering-session-instructions.md`. PRs #4, #5, #6.
- **Anthropic SDK 0.39 → 0.101 (httpx 0.28 compat)** — PR #4.
- **First GoDaddy deploy bug-fix bundle**
  (`APPLICATION_ROOT` double-prefix, path mismatch, cron path/import
  hardening, `_selftest.py`) — PR #3.
