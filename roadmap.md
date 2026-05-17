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
| 9 | 6 | backend, ui, new-feature, algo | Story dossier (multi-source view of a single story) | done |
| 8 | 7 | ops, backend, new-feature | Automated source discovery (Reddit/HN + LLM agent) | done |
| 7 | 7 | ops, new-feature | Automated source discovery — social firehoses (Mastodon, Bluesky, X/Twitter) | backlog |
| 8 | 7 | algo, backend, new-feature | Signal Learning (implicit + explicit reader signals → per-user adjustments) | backlog |
| 7 | 4 | security | CSRF tokens + auth rate limiting | done |
| 7 | 4 | algo | Fold internal clicks into popularity (superseded by Signal Learning) | backlog |
| 7 | 4 | ui | Mobile / responsive polish | done |
| 7 | 4 | new-feature, ui | Article summary (3-bullet TL;DR via Haiku) | backlog |
| 7 | 4 | ui, new-feature, algo | Reading diet meter | backlog |
| 7 | 5 | new-feature, algo | Trending topics view (upgraded post-dedup) | done |
| 7 | 4 | algo, backend, ui | External trending sort (Google News/Trends) — BUG-015 | done |
| 7 | 3 | ui | Why This Article (ranking explainer popover) | backlog |
| 7 | 3 | ui, algo | Across-the-spectrum in-feed (mini-dossier on multi-source cards) | in-progress |
| 7 | 3 | new-feature, ui, algo | Discussion links (Techmeme-style Reddit/HN threads) | done |
| 6 | 4 | new-feature, ui | Article save / bookmark | done |
| 6 | 4 | new-feature, ui | TTS audio mode (Read-me-my-queue) | backlog |
| 6 | 2 | ui, backend | Feed sort selector (Relevance / Newest / Popularity) | done |
| 6 | 4 | new-feature, ui | User-added RSS feed subscriptions | done |
| 6 | 6 | new-feature, ui | Search across articles | backlog |
| 5 | 5 | infra | Test coverage expansion | backlog |
| 5 | 3 | security | Email verification on signup | backlog |
| 5 | 1 | ops | CloudLinux/GoDaddy support ticket re: shim | backlog |
| 4 | 7 | infra, skunkworks | Migrate to VPS (gunicorn + nginx) | backlog |
| 3 | 2 | ui | Dark mode | in-progress |
| 8 | 5 | ui, algo, new-feature | Natural-language algorithm builder | done |
| 8 | 4 | algo, ui | Keyword / topic mute & boost | backlog |
| 7 | 4 | backend, ui | Multiple saved algorithms / profiles | in-progress |
| 6 | 5 | ui, algo | A/B split feed | backlog |
| 7 | 4 | ui, new-feature | Onboarding interview / cold-start | done |
| 7 | 4 | algo, ui | Tune from this article (Signal-Learning wedge) | backlog |
| 6 | 3 | ui, ops | Periodic "is your feed working?" check-in | backlog |
| 8 | 6 | new-feature, ui | Shareable algorithm gallery | backlog |
| 7 | 5 | algo, backend | Community source-quality overlay | backlog |
| 6 | 5 | new-feature | Community "add a source" on dossiers | backlog |

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
**Priority:** 9 · **LOE:** 6 · **Category:** backend, ui, new-feature, algo · **Status:** done (v1, PR #43)

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

### Automated source discovery — social firehoses
**Priority:** 7 · **LOE:** 7 · **Category:** ops, new-feature · **Status:** backlog

Phase 3 of source discovery. Adds three more signal sources to the
candidate pipeline shipped in the Reddit/HN + LLM PR:

- **Mastodon** — public timeline streaming per instance. Easiest, no
  API key needed. Start with a curated list of journalism-heavy
  instances (mastodon.social, journa.host, newsie.social).
- **Bluesky** — the jetstream firehose is a public WebSocket and
  doesn't fit the cron model cleanly; either a long-running worker
  process (new infra pattern) or a periodic batch pull of recent
  `app.bsky.feed.post` records with URLs.
- **Twitter/X** — only viable with a paid API tier ($100/mo Basic
  minimum for usable volume); gated on whether the catalog growth
  justifies the spend.

All three feed the same `candidate_sources` table; the only new code per
platform is a poll/stream worker. Hard-depends on the candidate_sources
schema landing first.

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
Also absorbs the principled follow-on to BUG-012's score-jitter
patch: a **per-user seen-recently downrank** (impression tracking on
card render, downweight for N hours after impression) so refresh
shuffle is informed by what the user has actually seen rather than a
uniform random nudge.

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
**Priority:** 7 · **LOE:** 5 · **Category:** new-feature, algo · **Status:** done (v1, PR #71)

> **Implementation note (2026-05-17):** the original plan piggybacked
> topic extraction on the `classify_pending` LLM call. That file is being
> rewritten by a parallel session (PR #56, BUG-016..019), so this session
> took the conflict-free route: reuse the Google Trends/News topic index
> `trending_poll` already builds every 30 min (PR #53), persist topic →
> article matches, and rank topics by distinct-outlet count. No
> `classify_pending` edit, no added LLM cost. Trade-off: only surfaces
> topics that are also externally trending (Google), not purely-internal
> ones — the LLM-entity upgrade remains the documented follow-on (pairs
> with Signal Learning entity extraction).

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
**Priority:** 7 · **LOE:** 3 · **Category:** ui, algo · **Status:** in-progress (PR #69)

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

### Fold internal clicks into popularity
**Priority:** 7 · **LOE:** 4 · **Category:** algo · **Status:** backlog

`user_clicks` is being recorded but isn't used in the ranking. Popularity
today is only Reddit + HN. Internal clicks are a stronger signal for our
users — fold them in.

Approach: per-article click-rate (clicks per impression over rolling 24h)
normalized to 0..1, max'd with the external signal so unpopular-on-Reddit-but-
popular-here articles still rank.

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

### Search across articles
**Priority:** 6 · **LOE:** 6 · **Category:** new-feature, ui · **Status:** backlog

Full-text search box in the nav, results page sorted by relevance + recency.
MySQL FULLTEXT index works for v1; revisit if quality is poor (then SQLite
FTS5 in-process, or Meilisearch on a VPS).

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
**Priority:** 3 · **LOE:** 2 · **Category:** ui · **Status:** in-progress

Toggle in the user nav. CSS custom-property swap. Persist preference in
`localStorage`.

---

## User-empowerment cluster (added 2026-05-17)

Themes A/B/C from the "empower the user to help us build the perfect
newsfeed" brainstorm. A = direct algorithm expressiveness; B = closing
the feedback loop; C = crowdsourcing the feed for everyone.

### Natural-language algorithm builder
**Priority:** 8 · **LOE:** 5 · **Category:** ui, algo, new-feature · **Status:** done (v1, PR #59)

User describes the feed they want in plain English ("more local tech and
science, less political outrage, prefer long objective reads, hide
paywalls"); a single Claude Haiku call maps that onto the existing
`FEATURES` catalog (direction / weight / threshold per feature, plus
recency) and the `/algo` UI is pre-filled with the proposed settings for
the user to review, tweak, and apply — never applied silently.

Reuses the Haiku client already wired for `political_lean` /
`objectivity` classification and dossier framing. The model returns
strict JSON constrained to the known feature names and the 3-axis
schema; out-of-range values are clamped, unknown keys dropped, and a
parse failure falls back to "couldn't parse that — editor unchanged"
rather than erroring. No per-request LLM cost (fires only on explicit
submit).

Biggest single unlock for non-technical users: turns the core "build
your own algorithm" thesis from a slider grid into a sentence. Pairs
with the read-only Code tab and is a natural precursor to Sandboxed
Python exec (Pri 9).

### Keyword / topic mute & boost
**Priority:** 8 · **LOE:** 4 · **Category:** algo, ui · **Status:** backlog

Per-user mute and boost term lists ("mute: crypto, royal family; boost:
climate policy, local elections") applied at the feed-query layer as a
hard filter (mute) and a score multiplier (boost). Distinct from
`user_source_prefs` (which weight whole sources) — this is
content/topic-level and the highest-perceived-control lever users ask
for first. New `user_term_prefs(user_id, term, mode, weight)` table;
matched against title + summary (+ body once extracted). v2: phrase /
entity-aware matching once topic extraction (Trending) lands.

### Multiple saved algorithms / profiles
**Priority:** 7 · **LOE:** 4 · **Category:** backend, ui · **Status:** in-progress

Named algorithm profiles ("Morning brief", "Weekend deep-dive", "Work
mode") switchable from a dropdown on `/`. Today there is exactly one
active `user_algorithms` row per user; this generalizes to many with an
`is_active` flag + `name` and a profile switcher. Pairs with the NL
builder (each generated algo can be saved as a profile) and time-of-day
auto-switching as a v2 follow-on.

### A/B split feed
**Priority:** 6 · **LOE:** 5 · **Category:** ui, algo · **Status:** backlog

Two algorithms rendered side by side over the same article pool so the
user can see concretely which tuning surfaces a better feed and promote
the winner to active in one click. Makes algorithm tuning empirical
instead of guesswork. Depends on Multiple saved algorithms for the
"promote winner" half; the compare view itself can ship first against
"current vs. a scratch algo".

### Tune from this article
**Priority:** 7 · **LOE:** 4 · **Category:** algo, ui · **Status:** backlog

Inline "more like this / less like this" on any feed card that, instead
of silently learning, *shows which feature weights it would nudge and by
how much* with accept / undo. Effectively the "Suggest" mode of the
larger **Signal Learning** item (Pri 8) but article-anchored and
immediate — can ship as the cheap standalone wedge for that theme and
later be absorbed into the full Signal Learning regression. Keep the two
in sync; don't double-implement the adjustment-vector storage.

### Periodic "is your feed working?" check-in
**Priority:** 6 · **LOE:** 3 · **Category:** ui, ops · **Status:** backlog

Lightweight in-feed card surfaced every N days: a 1–5 rating plus an
optional "what's missing / what's too much?" free-text box. Per-user it
feeds tuning suggestions; in aggregate it's the cheapest product-quality
signal (trend the mean, read the free-text for themes). Dismissible,
rate-limited per user so it never nags. New
`feed_feedback(user_id, score, note, created_at)` table.

### Shareable algorithm gallery
**Priority:** 8 · **LOE:** 6 · **Category:** new-feature, ui · **Status:** backlog

Users publish an algorithm with a name + short description; others
browse a gallery and one-click **adopt** or **fork** it. Network effect
(good feeds spread), a viral/marketing surface, and a corpus of what
users consider a good feed that can inform future default presets. The
code already has internal `PRESETS`; this exposes user-authored ones.
Needs a `shared_algorithms` table, a moderation/abuse story (report +
admin takedown), and adopt = clone into the user's own `user_algorithms`
(pairs with Multiple saved algorithms, which it depends on for clean
adopt/fork semantics).

### Community source-quality overlay
**Priority:** 7 · **LOE:** 5 · **Category:** algo, backend · **Status:** backlog

Aggregate the per-user trust/distrust + thumb signals already captured
in `user_signals` / `user_source_prefs` into a community bias /
reputation badge shown on cards, and (opt-in) fold it into the default
ranking so individual signal becomes a collective good. Main risk is
brigading: weight contributions by account age / activity, cap per-user
influence, and keep the community overlay separate from the editorial
`source_reputation` so it can be audited and disabled. Absorbs part of
the "Fold internal clicks into popularity" intent at the source level.

### Community "add a source" on dossiers
**Priority:** 6 · **LOE:** 5 · **Category:** new-feature · **Status:** backlog

On the story dossier (the killer-demo page), signed-in users can submit
a missing source/article URL for that story. Submissions flow into the
existing `candidate_sources` admin review queue (and, if the domain is
already a known source, just attach the article to the cluster).
Crowdsources coverage breadth exactly where missing perspectives are
most visible. Depends on Story dossier (done) and the discovery
pipeline's `candidate_sources` table (done).

---

## Done

Reverse chronological. Each entry links to the merged PR; the matching
narrative lives in `engineering-history.md` under the same date.

### 2026-05-17

- **Trending topics view** — Pri 7, LOE 5, new-feature/algo. PR #71
  (merged 2026-05-17). New `/trending` page ranking topics by
  distinct-outlet count ("20 outlets beat one outlet ×20"), each
  linking to the story dossier(s) under it. Reuses the Google
  Trends/News topic index `trending_poll` already builds (PR #53)
  instead of the roadmap's `classify_pending` LLM plan — chosen to
  avoid colliding with the in-flight `classify_pending` rewrite
  (PR #56) and add zero LLM cost. `trending_poll` now also rebuilds a
  `trending_topics` / `trending_topic_articles` snapshot each tick;
  new pure helpers in `app/trending.py` (`topic_key`, `topic_matches`
  — `score_article` refactored to its max, identical output —
  `build_persist_rows`, `group_topic_stories`). New blueprint +
  template + nav + additive CSS; env-defaulted `TRENDING_*` config.
  **Required one DB migration** (`2026-05-17-trending-topics.sql`,
  applied on prod 2026-05-17); **no new cron**. Limitation: only
  surfaces topics also trending on Google — the internal LLM-entity
  version is the documented follow-on (pairs with Signal Learning),
  deferred until PR #56 lands.
- **Article save / bookmark** — Pri 6, LOE 4, new-feature/ui. PR #64
  (merged 2026-05-17). Signed-in users star feed articles (☆/★ via
  the existing `cardSignals` Alpine component) into a new `/saved`
  page; new `saves` blueprint (`POST /save/<id>` toggle,
  `/save/<id>/read`, `GET /saved`). New `user_saves` table
  (`folder` default "Read Later"; `read_at` set on click-through).
  **Durable archive:** `jobs/maintenance.py` exempts saved articles
  (and their `article_bodies`) from both retention prunes, so the
  in-app reader copy stays readable indefinitely. v1 is a single
  implicit folder; folder UI / "N unread" prompt / export are v2.
  **Required a manual DB migration** (`2026-05-17-user-saves.sql`,
  load-bearing — see `manual-actions.md`).
- **Onboarding interview / cold-start** — Pri 7, LOE 4,
  ui/new-feature. PR #62. Theme A. Upgraded the bare `/algo/onboarding`
  preset picker into a real interview: topic categories (hard
  `category_filter`), a 5-point soft political-balance choice
  (`political_lean_direction`, no threshold so cross-spectrum exposure
  stays), and top-reputation trusted-source picks that get a
  `user_source_prefs` boost (weight 1.5, reuses the PR #19 feed
  multiplier). Answers layer on the `balanced` preset → one
  "My starting feed" `user_algorithms` row; signup now lands here;
  route is idempotent (re-visit after onboarding → editor). Pure logic
  in new Flask-free `app/onboarding.py`. **No** DB migration / cron /
  dep / env change.
- **Natural-language algorithm builder** — Pri 8, LOE 5,
  ui/algo/new-feature. PR #59. Plain-English feed description → one
  Claude Haiku call → the existing 3-axis `FEATURES` weight vector,
  pre-filling the `/algo` editor for review (never applied silently;
  reuses the existing `/save` path, so **no DB migration**). New
  Flask-free `app/algo_nl.py` (mirrors `classifier/framing.py`: lazy
  `anthropic`, `LLMUnavailable` on any failure, every value clamped
  into range, unknown keys dropped); `POST /algo/describe`
  re-renders the editor; "Describe your ideal feed" panel on the UI
  tab. Fails soft (no key / parse / API error → editor unchanged +
  inline note, never 500s); no per-request LLM cost. Shipped
  alongside a 10-item "user-empowerment" roadmap cluster (themes
  A/B/C). No new dep, no cron/env/symlink change.
- **Discussion links (Techmeme-style Reddit/HN)** — Pri 7, LOE 3,
  new-feature/ui/algo. PR #52. `popularity_poll` already matched
  Reddit/HN threads per article for the popularity score but
  discarded the permalink; now persists `permalink` + `subreddit` on
  `popularity_signals` and surfaces a compact
  `Discussion: Hacker News (142) · r/technology (89)` line on feed
  cards plus a panel on the story dossier (pure `app/discussion.py`
  helpers). Zero new API cost / no new dep; one nullable-column
  migration applied on prod. Follow-ons (user-gated): free Bluesky
  `searchPosts` harvest into the same surface; paid X/Twitter.
- **Engineering-history archive process** — ad-hoc, docs/infra. PR #51.
  `engineering-history.md` had grown to ~34.8K tokens, past the 25K
  single-`Read` ceiling, breaking the "read it end-to-end" onboarding
  step. Split into a condensed live file (~11K tokens: 3 newest entries
  full + a "Condensed history" digest + a durable "Load-bearing
  production state" section that never ages out) plus a byte-exact
  `engineering-history-archive.md` consulted on demand only. ~14K-token
  budget + the archive procedure documented in
  `engineering-session-wrapup.md` (Step 1b) and
  `new-engineering-session-instructions.md` (Step 1 + tl;dr). Docs-only;
  no DB/cron/symlink/env-var/pip change, no manual prod action.
- **External trending sort (Google News/Trends)** — Pri 7, LOE 4,
  algo/backend/ui. PR #53. Fixes BUG-015 (Popularity sort was
  HN-only). New `app/trending.py` (pure helpers) + `jobs/trending_poll.py`
  cron harvest Google Trends + Google News RSS into weighted topics and
  write a 0..1 `article_features.trending` column. The feed's
  `popularity` sort is renamed **Trending** and ordered
  `f.trending DESC, score DESC` — trending topics surface but the
  user's algorithm orders within them (relevance preserved). Opt-in
  `trending` feature in the catalog (default weight 0; existing user
  algos unchanged). Legacy `?sort=popularity` aliased to `trending`.
  No new pip dependency. **Requires manual DB migration**
  (`seed/migrations/2026-05-17-trending.sql`) + a new every-30-min
  cron entry. Does **not** supersede the separate "Trending topics
  view" item below (that's a dedicated `/trending` page).
- **CSRF tokens + auth rate limiting** — Pri 7, LOE 4, security. PR #58.
  Hand-rolled signed double-submit-cookie CSRF (stdlib `hmac`/`secrets`,
  zero new dependency) enforced on every unsafe-method route via an
  app-wide `before_request`. Token delivered to forms via a
  `csrf_field()` helper, to HTMX via an `htmx:configRequest` header
  hook, and to plain `fetch()` POSTs via a `<meta>` tag +
  `window.csrfToken`. RFC 8058 one-click `/account/unsubscribe`
  exempted (URL-token authenticated). `CSRF_ENABLED` config (default
  on; conftest disables suite-wide, `test_csrf.py` re-enables).
  Sliding-window in-process rate limit on `/auth/login` +
  `/auth/signup` (default 10 POSTs / 5 min per IP, env-tunable);
  per-worker caveat documented. No DB migration, no new dependency,
  no manual prod action — standard Python App restart on deploy.

### 2026-05-14

- **Feed sort selector (Relevance / Newest / Popularity)** — Pri 6, LOE 2,
  ui/backend. PR #48. Adds a `?sort=` query param to `/`: `relevance`
  (default — score DESC, current algo-driven order), `newest`
  (`a.published_at DESC, score DESC`), `popularity` (`f.popularity DESC,
  a.published_at DESC`). Threshold filters and the user's algorithm
  weights still apply to every sort — only the ORDER BY changes.
  Pure URL-param persistence (no DB migration). Selector preserves the
  active category and threads through HTMX "Load more". Unknown values
  fall back to `relevance`. No new dependency. CSS-only template edits
  (single `.feed-controls` flex row in `style.css`).

### 2026-05-13

- **English-only article filter at fetch time** — ad-hoc, ops/backend.
  PR #42. New `app/language.py` with pure-Python `is_english()` that
  trusts non-English RSS `<language>` tags and otherwise rejects on a
  >25% non-Latin letter ratio in title+summary. Wired into
  `fetch_feeds.py` before the INSERT; rejected entries surface as
  `skipped_lang=N` in the per-tick summary. No DB migration, no new
  dependency. Latin-script European content (FR/DE/ES/IT) still
  slips through unless the feed self-declares — limit documented in
  INSTALL.txt §10.
- **Mobile / responsive polish** — Pri 7, LOE 4, ui. PR #40. Single
  additive `@media (max-width: 640px)` block in `app/static/style.css`
  plus a `.table-scroll` utility — desktop layout untouched. Collapses
  `.topnav` to wrap, `.algo` two-column grid to single, `.feature-row`
  to stacked sliders; gives `#firehose-feed` `overflow-x: auto` with a
  `min-width: 640px` table; stacks `.admin` + `.admin-nav`; enlarges
  tap targets on `.cat-tab`, `.thumb-btn`, `.tabs button`; tightens
  `.auth-form`, `.onboarding`, `.preset-card`. CSS-only — no DB
  change, no cron, no pip dep.
- **Automated source discovery (Reddit/HN + LLM agent)** — Pri 8, LOE 7,
  ops/backend/new-feature. PR #38. New `candidate_sources` table; three
  cron jobs (`discover_harvest` hourly, `discover_promote` nightly,
  `discover_llm` weekly); `/admin/discovery` review queue with one-click
  approve / reject / blacklist. Pure helpers in `app/discovery.py`.
  Promotion gated behind admin review by default. Phase 3 (social
  firehoses) backlogged separately. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-discovery.sql`) and three new cron entries.
- **Article deduplication across sources** — Pri 8, LOE 7, algo/backend. PR #24.
  `articles.story_id` + `articles.simhash` columns; `fetch_feeds` computes
  64-bit SimHash on title+summary lead; `classify_pending` per-article cluster
  assignment via title_hash exact match OR SimHash Hamming<=8 over 48h window;
  canonical = highest source_reputation, oldest tiebreak. Feed dedupes by
  story_id, firehose stays un-deduped. Heavy paraphrases left to a future
  embedding-based pass. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-dedup.sql`).
- **User-added RSS feed subscriptions** — Pri 6, LOE 4, new-feature/ui.
  PR #29. New `/sources` page, signed-in users add personal feeds
  scoped via `sources.owner_id`; feed/firehose queries filter by
  visibility. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-user-sources.sql`).
- **In-app reader view (body extraction + `/read/<id>`)** — Pri 8, LOE 6,
  backend/new-feature/ui. PR #21. New `article_bodies` table, trafilatura
  extractor wired into `classify_pending` (paywall-aware, shares the
  cron wallclock budget), `/read/<id>` blueprint + reader template,
  nightly `BODY_RETENTION_DAYS` prune in `maintenance.py`, single `Read →`
  link in `card-meta`. **Requires manual DB migration**
  (`seed/migrations/2026-05-13-article-bodies.sql`) and `pip install -r
  requirements.txt` (adds `trafilatura==1.12.2` + `lxml`) on cPanel,
  then Python App restart.
- **Daily personalized email digest** — Pri 6, LOE 7, new-feature/infra.
  PR #23. Opt-in toggle on `/account/settings`, `users.digest_enabled`
  + 40-hex unsub token, noon-UTC cron `jobs/send_digest.py` reusing the
  feed's ranking SQL, MIME alternative HTML+text via stdlib `smtplib`
  (localhost MTA by default). One-click List-Unsubscribe header wired.
  **Requires manual DB migration** (`seed/migrations/2026-05-13-digest.sql`)
  and a new noon-UTC cron entry.
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
