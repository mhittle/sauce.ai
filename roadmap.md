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
| 9 | 6 | backend, ui, new-feature, algo | Story dossier (multi-source view of a single story) | backlog |
| 8 | 7 | algo, backend | Article deduplication across sources | backlog |
| 8 | 7 | algo, backend, new-feature | Signal Learning (implicit + explicit reader signals → per-user adjustments) | backlog |
| 8 | 6 | backend, new-feature, ui | In-app reader view (body extraction + sauce.ai/read/<id>) | in-progress |
| 7 | 4 | security | CSRF tokens + auth rate limiting | backlog |
| 7 | 4 | algo | Fold internal clicks into popularity (superseded by Signal Learning) | backlog |
| 7 | 4 | ui | Mobile / responsive polish | backlog |
| 7 | 4 | new-feature, ui | Article summary (3-bullet TL;DR via Haiku) | backlog |
| 7 | 4 | ui, new-feature, algo | Reading diet meter | backlog |
| 7 | 5 | new-feature, algo | Trending topics view (upgraded post-dedup) | backlog |
| 7 | 3 | ui | Why This Article (ranking explainer popover) | backlog |
| 7 | 3 | ui, algo | Across-the-spectrum in-feed (mini-dossier on multi-source cards) | backlog |
| 6 | 4 | new-feature, ui | Article save / bookmark | backlog |
| 6 | 4 | new-feature, ui | TTS audio mode (Read-me-my-queue) | backlog |
| 6 | 4 | new-feature, ui | User-added RSS feed subscriptions | backlog |
| 6 | 6 | new-feature, ui | Search across articles | backlog |
| 6 | 7 | new-feature, infra | Daily personalized email digest | backlog |
| 5 | 5 | infra | Test coverage expansion | backlog |
| 5 | 3 | security | Email verification on signup | backlog |
| 5 | 1 | ops | CloudLinux/GoDaddy support ticket re: shim | backlog |
| 4 | 7 | infra, skunkworks | Migrate to VPS (gunicorn + nginx) | backlog |
| 3 | 2 | ui | Dark mode | backlog |

---

## Items in detail

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

### Story dossier
**Priority:** 9 · **LOE:** 6 · **Category:** backend, ui, new-feature, algo · **Status:** backlog

`sauce.ai/news/story/<story_id>` aggregates every article in a
deduplicated story group and presents them across the political-lean
spectrum — three columns (left / center / right) on desktop, vertical
bands on mobile. Each column shows source headline, lead paragraph,
and a small lean badge.

Sticky element at top: a Claude-generated **framing summary** — *"Left-
leaning sources emphasized the demographic impact; right-leaning
emphasized the procedural concerns; AP and Reuters stuck to the
announcement itself."* Cached per story group, recomputed only when
new articles join.

Optional power feature: word-level diff highlights between headlines
and lead paragraphs so coverage divergence is *visible* ("the suspect"
vs "the gunman" vs "the alleged shooter"). This is the screenshot
that gets shared.

This is the **killer demo**. No other aggregator does this — and it's
the feature that requires our opinionated multi-source backend. Without
it, sauce.ai is a slightly nicer Google News; with it, a category of
one.

Cost gating: only run framing summaries for story groups with 3+
articles spanning 2+ lean buckets. Single-source stories don't get a
dossier — their card just links to the source.

Hard dependency on **Article deduplication** (Pri 8) — story_id must
exist first.

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

### Signal Learning
**Priority:** 8 · **LOE:** 7 · **Category:** algo, backend, new-feature · **Status:** backlog

Capture every reader signal in a uniform `user_signals` table — `click`,
`dwell_ms`, `scroll_pct`, `thumb_up`, `thumb_down`, `save`, `share`,
`hide`, `return_click`. Nightly job in `maintenance.py` regresses signals
against feature values per user, producing a hidden per-user adjustment
vector that rides alongside the explicit `/algo` weights.

Forward-compatibility (key design constraint): when a new ranking
feature lands later, `maintenance.py` back-classifies historical
articles within a rolling window so the user's accumulated signal
history informs the new dimension immediately. Same pattern as the
obscurity-score backfill, generalized via a `features.added_at` column
+ rescore queue. This means future features instantly benefit from
months of past reader behavior instead of needing fresh data to be
useful.

Two UX modes, staged:
- **Suggest (v1)** — "You read 3x more high-objectivity articles than
  the median. Bump objectivity weight to 1.5? [accept / dismiss]". User
  stays in control; learning is a recommender, not a silent rewriter.
- **Auto-tune (v2)** — hidden adjustment applied silently to ranking,
  exposed on `/algo` as a "Learned tweaks" panel the user can audit and
  reset to zero.

Absorbs the older Pri-7 "Fold internal clicks into popularity" item —
click signal becomes one input among many in the unified signal table.

Ship after Thumbs Up/Down so explicit signals are flowing first.

### Reading diet meter
**Priority:** 7 · **LOE:** 4 · **Category:** ui, new-feature, algo · **Status:** backlog

Personal-stats page at `/me/diet` showing the user a mirror of their
own reading over rolling 7-day and 30-day windows. Metrics:

- Political lean distribution ("68% center-left, 22% center, 10% right")
- Source diversity (unique sources, unique categories)
- Source reputation mix (mean / median)
- Reading level + info density distribution
- Paywall exposure ("47% of your reading was behind paywalls")
- Category breakdown
- Comparative deltas vs. the user's prior week

v2: weekly in-app card or email *"Your reading week in numbers"* —
Spotify-Wrapped energy, but truthful rather than gamified. v3:
comparative ("vs. the median sauce.ai reader") if presentable without
turning into a leaderboard.

Why it's sticky: gives the user a literal feedback loop on whether
their news diet matches their intent. Pairs naturally with Signal
Learning — "we noticed you only read center-left this week; here are
3 center-right pieces you might find worth your time".

Depends on signal capture (user_clicks today; user_signals once Signal
Learning lands).

### Trending topics view
**Priority:** 7 · **LOE:** 5 · **Category:** new-feature, algo · **Status:** backlog

`/trending` groups today's stories by topic/entity with source count.
Big upgrade post-dedup: trending becomes "topics that hit N outlets"
rather than "topics with N raw articles", so wire-syndicated noise
stops dominating. A topic that 20 outlets cover ranks above one that
one outlet covered 20 times.

Topic/entity extraction piggybacks on the existing `classify_pending`
LLM call (same body, additional output field — negligible incremental
cost given the call is already batching). Store as
`article_topics(article_id, topic)` many-to-many. `/trending` SQL
aggregates by recent article count and unique-source count.

Pairs with story dossier — each trending topic links to the
dossier(s) under it. Pairs with diet meter — "trending in your top
categories".

Bumped from Pri 5 to Pri 7 because the dedup-enabled version is much
stronger than the v1 version, and because it feeds the dossier theme.

### Why This Article
**Priority:** 7 · **LOE:** 3 · **Category:** ui · **Status:** backlog

Small "i" icon on each card → popover showing the top 3 feature
contributions to that article's score, plus learned-model influence
when present: "high objectivity (+0.34), low paywall (+0.12), your
reading history (+0.08)".

Implementation: `/article/<id>/explain` endpoint fetches the article's
feature row, computes weighted contributions against the user's algo,
returns JSON. Frontend renders in a popover. Doubles as an admin debug
tool for tuning the ranking function.

Trust + transparency feature — also makes thumbs-down decisions more
informed ("oh, it ranked high because of X, but I don't actually care
about X").

### Across-the-spectrum in-feed
**Priority:** 7 · **LOE:** 3 · **Category:** ui, algo · **Status:** backlog

The lightweight everyday cousin of the story dossier. Every card on
the main feed that's part of a multi-source story gets a small
"+3 other angles" affordance under the headline. Click expands inline
to show 2-3 alternative source perspectives without leaving the feed.
A "Full dossier →" link inside the expansion takes the user to the
dossier page for the deep dive.

Why have both: dossier is *destination* content (you go there to
research a story); in-feed compare is *ambient* (you encounter it
while skimming and it nudges you to broaden one story at a time).
The in-feed version has much more surface area — every multi-source
card carries it.

Shares all the infrastructure of story dossier (story_id, source
clustering, source_lean), so essentially free once dossier exists.
Could ship before the full dossier page as a faster wedge into the
"multi-source view" idea.

Depends on Article deduplication (story_id). Pairs with Story dossier.

### In-app reader view (with body extraction)
**Priority:** 8 · **LOE:** 6 · **Category:** backend, new-feature, ui · **Status:** in-progress

`sauce.ai/news/read/<article_id>` renders the article body inside our
own typography and chrome. Pipeline change: `classify_pending` (or a
sibling job) runs `trafilatura` on the article URL post-fetch, extracts
main body text + author + lead image, stores in a new `article_bodies`
table kept separate from the main row so `articles` stays lean. Card
click is configurable per-user — go to source (today), or stay in the
reader.

Why it's foundational, not just another feature:
- **Retention.** Reader stays on `sauce.ai` instead of bouncing to a
  17-tracker NYT page. Biggest single retention lever in this theme.
- **Body text unlocks downstream features.** Better classification
  (Flesch-Kincaid is much more accurate on body than RSS summary),
  better dedup, article summaries, TTS, full-text search — all chain
  off having the body locally.
- **Typography continuity.** The "discerning reader" aesthetic from
  the PR-#13 wordmark extends into the actual reading moment.

Tradeoffs:
- Extraction success ~85-90% across the wild web. Paywalled bodies
  aren't extractable; fall through to source link in that case.
- Some sites' ToS technically disallow reformatting. Low practical
  risk at our scale but worth noting.
- Storage: ~5-30 KB/article × N articles/day adds up. Ship with a
  30-day retention window on bodies and prune in `maintenance.py`;
  bookmarked articles get longer retention (see Article save).

Subsumes the older Pri-6 "Full-text article extraction" item.

### Article summary
**Priority:** 7 · **LOE:** 4 · **Category:** new-feature, ui · **Status:** backlog

3-bullet TL;DR per article, generated by Claude Haiku at classification
time and cached on the row. Surfaces on card hover/expand (preview
without commitment) and at the top of the reader view (decide whether
to keep reading).

Batches with the existing political_lean / objectivity LLM call — same
body, one prompt, three judgments returned together. Cheaper than a
separate call. Gate to control cost: only summarize articles passing a
threshold (e.g. `source_reputation > 0.4` AND `paywall < 0.5`). At
~$0.001-0.002 per article with Haiku, ~$1-3/day at expected volume.

v2: "Summarize today's brief" — meta-summary across the day's 10
articles for a 3-minute orientation read at the top of the home feed.

Depends on reader view body extraction (RSS blurbs make poor input).

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

### Article save / bookmark
**Priority:** 6 · **LOE:** 4 · **Category:** new-feature, ui · **Status:** backlog

Star/bookmark button on each card, `/saved` page in the nav, optional
folders (default "Read Later" + user-created). New table
`user_saves(user_id, article_id, saved_at, folder, read_at)`.

The real unlock is pairing with reader view: today, a bookmarked link
can rot (article deleted, URL changed, paywall hardened a month
later). With body extraction in place we already have the article body
stored at save-time, so bookmarks become a durable personal archive —
"owned by me" sticky, not a fragile URL list. Bookmarked articles get
extended retention on `article_bodies` so the reader-view copy stays
readable indefinitely.

Power features for v2: keyboard shortcut to save (`s`), bulk move
between folders, export saved as Markdown or OPML, "5 unread in your
Read Later" prompt on home when the queue grows.

Sequencing: ship after reader view + summaries so bookmarks are
durable from day one, before TTS so Read-me-my-queue has content to
play.

### TTS audio mode
**Priority:** 6 · **LOE:** 4 (v1) / 6 (v2) · **Category:** new-feature, ui · **Status:** backlog

"Play" button on the reader page and on each card.

- **v1:** browser `window.speechSynthesis` — free, zero infra. Decent
  on Chrome/Safari, mediocre elsewhere. Ship first to validate the use
  case before paying for quality.
- **v2:** server-side TTS (ElevenLabs / OpenAI `gpt-4o-mini-tts` /
  Google) generating MP3 cached per-article. High quality, ~$0.005-0.02
  per article — gate behind a "premium" tier or "top-rated articles
  only" before turning on broadly.

The sticky pattern: a **"Read me my queue"** button on `/saved` that
plays the Read Later queue back-to-back, podcast-style. Commute /
exercise / dishes use case — earbuds in, sauce.ai becomes the source
for 20 minutes. Podcast-mode listening is habit-forming in a way visual
reading isn't.

v2+ extras: per-article duration estimate ("~4 min read · ~5 min
listen"), lock-screen media controls via Media Session API, skip-to-
next, playback speed.

Depends on reader view body extraction.

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

### 2026-05-13

- **Thumbs up/down on cards** — Pri 7, LOE 4, ui/algo. PR #19. Adds the
  generic `user_signals` table (forward-compat for Signal Learning) +
  `user_source_prefs`. Subtle hover-revealed chevrons, toggle semantics,
  3-downs-from-source prompt with Less / Hide / Reset actions, feed
  query splice that filters/multiplies by per-user-source weight.
  **Requires manual DB migration** (`seed/migrations/2026-05-13-signals.sql`).
- **Cron job hardening: timeouts + flock** — Pri 8, LOE 3, infra. PR #15.
  Per-job fcntl mutex, requests timeouts on RSS/Reddit/HN, HN wallclock
  budget, anthropic `timeout=30`, `FEED_FETCH_BATCH` 80→20.
- **PyMySQL connection timeouts** — Pri 8, LOE 2, backend. PR #15 (same
  PR). Web path `(5,15,10)`, cron path `(5,30,15)`.

### 2026-05-12

- **Paywall feature (per-article detection)** — Pri 7, LOE 4, algo/new-feature.
  PR #14. Active HTTP probe during `classify_pending` writes a 0..1 paywall
  score; opt-in catalog entry; admin /feeds gets a paywall column.
  **Requires manual DB migration** (`seed/migrations/2026-05-12-paywall.sql`).
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
