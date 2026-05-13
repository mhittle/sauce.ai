# sauce.ai/news — Engineering history

Chronological log of architecture decisions, bugs hit, and fixes applied to
sauce.ai/news. **Read end-to-end before making changes.** Append a new dated
section whenever something meaningful happens — see
`new-engineering-session-instructions.md` for what counts as "meaningful".

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
