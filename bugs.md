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

### BUG-031 — Anonymous `/` (home feed) returns HTTP 500 after the PR #145 deploy
**Status:** open · **Reporter:** post-deploy QA agent (was PR #147, closed) · **Opened:** 2026-05-31
**Note:** originally auto-filed by the QA agent as a draft PR (#147) that
labeled this "BUG-028"; that number was already taken on `main` by the "Why?"
explainer 500 (now Resolved). Re-filed here as **BUG-031** to avoid the
collision; PR #147 was closed and folded into this entry.

The post-deploy QA agent reports anonymous `GET https://sauce.ai/news/`
returning **HTTP 500** consistently (generic LiteSpeed/Apache 500 page, no app
output), while `/auth/login` and `/firehose` return **200**. Deploy HEAD was
`70e0516` (merge of PR #145, the 3-bullet TL;DR feature). The "only `/` 500s
while other routes are healthy" signature is the classic **BUG-007 class**
pattern — the feed route references prod state that the other routes don't.

**Leading hypotheses (ranked), to confirm with prod telemetry:**
1. **`article_summaries` migration still unapplied + a code-path gap.** PR #145
   added the TL;DR read path (`feed.summary` route + a feed-card toggle). The
   migration (`2026-05-31-article-summaries.sql`) is still **Open** in
   `manual-actions.md`. The read path is *supposed* to degrade gracefully on a
   missing table (`load_bullets` catches it), but a 500 on the full `/` render
   suggests a gap in that guard on the feed-index path specifically. **Cheapest
   to check first** — apply the migration (Open manual-action) and re-test.
2. **Stale Passenger worker after the #144/#145 deploy.** PR #144 (feed
   SELECTION/RANKING split, `feed.index()` rewrite + new `FEED_SELECTION_POOL`
   config) and PR #145 both need a **Python App restart** (Open in
   `manual-actions.md`). A half-loaded worker serving a new template against an
   old route — or a config key read before restart — can 500 `/` while the
   unchanged `/auth/login` and `/firehose` stay up.
3. **A genuine exception in the new `feed.index()` affinity/diversify path**
   (PR #144) on the anonymous/default-weights branch — would show as a Python
   traceback in `~/public_html/sauce.ai/news/logs/`.

**Diagnostic (prod):**
```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://sauce.ai/news/            # expect 200, currently 500
tail -100 ~/public_html/sauce.ai/news/logs/*.log                            # look for the feed-route traceback
```
```sql
SHOW TABLES LIKE 'article_summaries';   -- hypothesis 1: missing => apply the Open migration
```

**Fix (pending prod action):** work the two Open `manual-actions.md` items in
order — (a) apply the `article_summaries` migration, (b) restart the Python App
(the restart also covers PR #140/#144) — then re-test `/`. If `/` still 500s
after both, pull the traceback from `logs/` and escalate to hypothesis 3
(the `feed.index()` affinity path). Status stays `open` until prod confirms `/`
returns 200.

### BUG-029 — NL algorithm builder (chat box) does not create keywords for the specific algorithm
**Status:** in-progress (prompt-hardening fix written, PR pending; prod re-test pending) · **Reporter:** user · **Opened:** 2026-05-31
**Note:** renumbered from BUG-028 → BUG-029 on 2026-05-31 to resolve a
parallel-session BUG-ID collision (a session merged to `main` used BUG-028
for the "Why?" ranking-explainer 500). See
`new-engineering-session-instructions.md` §7.4. Original commit/PR #142
text may still say BUG-028.

User reports that entering algorithm preferences through the `/algo`
natural-language chat box ("describe your algorithm") does **not** create
keywords for that specific algorithm. Expected: a description like "more
climate policy, hide crypto" should produce per-algorithm keyword
mute/boost entries (in `algorithm_term_prefs`) attached to the active
profile, in addition to moving the feature sliders.

**Context (recent change, possibly unshipped):** the 2026-05-27
engineering-history entry ("NL algorithm builder now also proposes
keywords") describes exactly this capability — the single Haiku call in
`app/algo_nl.py` was extended to also return a `keywords` list, rendered
as removable pending chips in `#algo-form` and persisted only on **Save
algorithm** / **Save as new profile** (owner chose review-then-Save). That
work was logged as **PR pending** and may not be merged/deployed yet.

**Hypotheses to confirm (ranked):**
1. The keyword-proposal PR is still pending / not deployed to prod, so the
   chat box maps onto sliders only (the pre-2026-05-27 behavior).
2. The PR is deployed but keywords don't persist — e.g. the pending chips
   render but `_apply_nl_keywords()` isn't invoked on Save, or the hidden
   `nl_kw_*` inputs aren't submitted with the form.
3. The Haiku call isn't returning a `keywords` list (prompt/parse issue),
   so no chips ever appear to save.
4. User expectation mismatch: keywords are proposed as review-then-Save
   chips and only persist on an explicit Save — if the user described and
   didn't Save, nothing is written. Need to confirm the user's exact flow.

**Repro (to confirm with user):** go to `/algo`, type a description that
names topics to favor/hide into the chat box, submit; check whether
keyword chips appear and whether they persist to the profile after Save.

**Investigation (2026-05-31):**
- Code on `main` (PR #140, merged via d0b2457) is correct: `algo_nl.py`
  returns a sanitized `keywords` list; `routes/algo.py` `describe()` passes
  it as `nl_keywords`; `algo.html` renders the chips with hidden `nl_kw_*`
  inputs **inside** `#algo-form`; both `save()` and `create_profile()` call
  `_apply_nl_keywords()`. `test_algo_nl.py` 21/21 green in sandbox (route
  layer not runnable here — no flask/pymysql, documented limitation).
- **User confirmed: no keyword chips appear after "Build from
  description", and the keywords are still absent after a full reload.**
  This **rules out hypothesis 2/4** (the refresh gap would save-but-not-
  show; a reload would then reveal them). The route is returning **no
  keywords to render** in the first place.
- **Leading cause → hypothesis 1 (stale Passenger worker).** PR #140 is on
  `main` and auto-deploys, but the new `describe()` Python route needs a
  **Passenger restart** to take effect (Jinja auto-reloads the template, so
  the chip block is present, but the *old* route passes it no `nl_keywords`
  → `kws=[]` → `x-show="kws.length"` false → no chips, even on reload —
  exactly the reported symptom). No `manual-actions.md` Open entry was
  created for the PR #140 restart (process gap, same class as BUG-007/025).
  Secondary possibility (hypothesis 3): route is live but Haiku omits the
  `keywords` array — distinguishable only after a restart confirms the new
  route is serving.

**Fix (pending user action):** restart the `sauce.ai/news` Python App in
cPanel (added as an Open entry in `manual-actions.md` 2026-05-31, with
verification), then re-test the describe flow. If chips still don't appear
after a confirmed restart, escalate to hypothesis 3 (inspect the prompt/
parse against live Haiku output). Status stays `open` until prod confirms
chips render and keywords persist to the profile.

**Re-report + code re-verification (2026-05-31, continued):** user reports
the keywords are **still not set by the prompt** on `/algo`. Re-audited the
entire merged chain on `main`/this branch (PR #140 = commit `d2e4da5`, present
in history) end-to-end — it is correct:
- `app/algo_nl.py` `_system_prompt()` instructs a `keywords` array;
  `_normalize_keywords()` sanitizes via `term_prefs` helpers; `_normalize()`
  returns the list and `interpret_algorithm()` surfaces it.
- `routes/algo.py` `describe()` passes `nl_keywords=result.get("keywords")`;
  `_render_editor` forwards it; `save()` + `create_profile()` both call
  `_apply_nl_keywords()` (which re-sanitizes the submitted `nl_kw_*` inputs).
- `templates/algo.html` renders the chip block (`x-for` over `kws`) with the
  hidden `nl_kw_term/mode/weight` inputs **inside** `#algo-form` (opens L27,
  closes L173); "Save algorithm" uses `hx-include="#algo-form"`, "Save as new
  profile" is a plain submit inside it — so the chips ride along on either save.
This **re-confirms the bug is not in the repo code**; the two live hypotheses
remain (1) the PR #140 Passenger restart was never done (the `describe()`
route is still the pre-#140 build serving no keywords), or (3) the worker is
fresh but Haiku is omitting the `keywords` array. These are distinguished only
by prod facts I can't observe from the sandbox (no Flask/DB/LLM/browser).
Awaiting user confirmation of (a) whether the Python App has been restarted
since PR #140 deployed and (b) whether chips appear at all vs. appear-but-
don't-persist, before either pointing at the restart or hardening the
`algo_nl.py` prompt for (3).

**Disambiguated + fix (2026-05-31, PR pending):** user confirmed (a) the
Python App **has** been restarted since PR #140 and (b) **no chips appear at
all** (none after reload). That eliminates hypotheses 1 (stale worker) and 2
(persistence) and confirms **hypothesis 3** — the live `describe()` route runs
but `interpret_algorithm()` returns an empty `keywords` list (Haiku sets the
sliders but omits the array). Root cause is the prompt, not the code: in
`app/algo_nl.py` `_system_prompt()` the `keywords` field was labeled
`OPTIONAL`, buried among the "Also:" bullets, and the prompt told the model
**twice** it could leave the list empty, so Haiku reliably did. **Fix
(`app/algo_nl.py`):** keywords reframed as a FIRST-CLASS, mandatory-when-a-
subject-is-named output (emit a keyword *in addition* to moving the sliders),
the empty-list caveat narrowed to purely-abstract descriptions, a second
worked example added, and a fully-populated worked-example JSON appended at
the schema tail. Also added an `algo.describe nl_keywords=%d` INFO log in
`routes/algo.py` `describe()` so prod logs show whether Haiku now returns
keywords (this bug stayed invisible across sessions because the model's output
was never observable). New guard test in `tests/test_algo_nl.py` fails if the
prompt regresses to "OPTIONAL". **Prod actions:** deploy this PR, then
**restart the Python App** (the new prompt is in the worker-loaded
`algo_nl.py`) — `manual-actions.md` Open. Stays `in-progress` until a prod
re-test shows chips rendering; if still empty after the restart, the
`nl_keywords=0` log line confirms it's a model-output problem to escalate
against the prompt/parse rather than the deploy.

**Still broken after PR #162 restart -> parser was too rigid (2026-05-31, PR
pending).** User confirmed the app was restarted after PR #162 merged and chips
*still* don't appear. That rules out the prompt being the sole cause and exposed
the real failure mode: `algo_nl._normalize_keywords` only accepted a `list` of
`dict`s with exactly `term` + `mode in {mute,boost}` and **silently dropped
everything else**. Haiku frequently returns a tolerable-but-different shape —
mode-keyed buckets `{"boost":[...],"mute":[...]}`, the term under
`keyword`/`phrase`/`topic`, the mode under `action`/`type`, or synonyms like
`hide`/`more`/`exclude` — all of which the old parser discarded, producing empty
keywords no matter how forcefully the prompt asked (which is why two prompt
iterations didn't help). **Fix:** rewrote `_normalize_keywords` to accept a
list OR a mode-keyed dict OR a single keyword object; pull the term from any of
several key names; map mode synonyms via `_MODE_SYNONYMS`; bare strings with no
inferable mode are still dropped (never guessed). `interpret_algorithm` now also
returns `keywords_raw` (the pre-normalization payload) and `describe()` logs it
truncated when the normalized list is empty (`algo.describe nl_keywords=0 raw=…`)
plus a distinct log on the `LLMUnavailable` branch — so if it STILL fails we can
finally tell model-returned-nothing from shape-we-failed-to-parse from
LLM-down. 4 new shape tests; all `_normalize_keywords` cases (incl. backward
compat) pass in-sandbox. **Prod action unchanged:** restart after this
follow-up PR deploys, then re-test.
### BUG-030 — Switching to an orthogonal algorithm surfaces largely the same articles
**Status:** resolved (PR #144 merged 2026-05-31; prod restart + browser verify pending) · **Reporter:** user · **Opened:** 2026-05-31 · **Closed:** 2026-05-31
**Note:** renumbered BUG-028 → BUG-029 → **BUG-030** on 2026-05-31 to clear
a cascade of parallel-session BUG-ID collisions: BUG-028 was taken by a
merged session's "Why?" ranking-explainer 500 (see Resolved), and BUG-029
by a merged session's "NL builder chat box keywords" bug (above). See
`new-engineering-session-instructions.md` §7.4. PR #144 title/commits may
still say BUG-028/BUG-029.

User reports that loading one algorithm and then switching to a
*different, supposedly orthogonal* algorithm shows "a lot of the same
articles." Expectation, in the user's framing: **weights decide what's
in the list (membership/selection); ranking decides the order**. Two
orthogonal algorithms should therefore produce visibly different
*sets*, not just a reordering of one set.

**Root cause (confirmed by code review — no crash/arithmetic bug, a
design conflation):**
1. **Weights only reorder; they never select.** The `/` candidate set
   (`routes/feed.py:index()`) is the *entire* `classified`, canonical,
   7-day, visible pool minus the *hard filters* in
   `ranking.build_filters_sql` (per-feature thresholds, category/country/
   geo, source-deny). A normal saved algo sets none of those, so two
   algos draw from an **identical** pool and the weight vector only feeds
   a single `score` used for `ORDER BY`. There was no selection stage
   distinct from the score — exactly the opposite of the user's model.
2. **The multiplicative recency gate dominates and homogenizes the top.**
   `score = quality * EXP(-recency_w * hours / 24)` (`ranking.py`). At the
   default `recency=0.7` the multiplier is ~1.0@0h, 0.5@24h, 0.25@48h,
   ~0.05@4d, so the freshest articles float up almost regardless of
   weights — weights only break ties among similar-age rows. Biggest
   single driver of the overlap (side effect of the BUG-011 fix).
3. **No penalty axis; presets all point the same way.** Each feature
   contributes `w * (1 - |value-dir|/scale) ∈ [0, w]` (always ≥ 0) and
   the presets/defaults all push objectivity / source_reputation /
   info_density "high," so a fresh reputable story scores well under
   nearly *any* algo. Orthogonal intents don't repel each other's picks.

**Fix (PR #144, merged 2026-05-31) — separate SELECTION from RANKING (owner chose this):**
- New `ranking.build_affinity_sql(weights)`: the **selection** signal — an
  L1-normalized, recency-free weighted feature match in `[0,1]`. Returns
  `("1", {})` when no feature is weighted.
- `routes/feed.py:index()` now: SELECT both `affinity` and the existing
  recency-gated `score`, `ORDER BY affinity DESC ... LIMIT FEED_SELECTION_POOL`
  to pick the **candidate SET** (membership = what's *in* the list), apply
  the per-source cap to that set, then **re-order** it by the user's sort
  via a new pure `feed_diversify.rank_for_display(rows, sort)`
  (relevance→recency-gated score, newest→published_at, trending→trending).
  Two orthogonal algos now select genuinely different sets.
- Recency moves to the *ranking* stage only: it no longer shapes
  membership, so an algo can surface older content it is most affine to,
  freshest-first. Does **not** regress BUG-011 (ordering is still
  recency-gated). New `FEED_SELECTION_POOL` config (default 600, clamped
  at `MAX_FETCH_ROWS`).
- Scope: `/` only — firehose, `/search`, `/saved`, `/algo` preview, and
  the digest keep the single-score `build_score_sql` model (same scoping
  as BUG-021/BUG-027). No DB migration, no cron, no new dep.

**Verification:** pure unit tests for `build_affinity_sql` (normalization,
empty-weights sentinel) and `rank_for_display` (per-sort order) run in the
sandbox. Route+DB behavior (set actually differs between two saved algos)
deferred to a real env / browser — same sandbox limitation noted on prior
feed-route PRs. Merged through 4 rebases all green on the BUG-007 gate.
**Remaining (prod):** Passenger restart so the new `feed.index()` route
serves (shared with the PR #140/#145 restarts already pending in
`manual-actions.md`), then switch between two orthogonal saved profiles on
`/` and confirm the article *set* differs — tracked as a `manual-actions.md`
Open entry (2026-05-31). Flip the prod-verify caveat off this entry once
confirmed.

---

### BUG-023 — Article classification rate stalls again after recent throughput fix
**Status:** open · **Reporter:** user · **Opened:** 2026-05-27

User reports that a fix earlier appeared to improve the article
classification rate, but it now seems stalled again. Symptom is observed
on prod; not reproducible from the sandbox (no DB / cron / Anthropic /
logs access).

**Context (recent classification-path changes):** BUG-008/009 (PR #32)
took throughput 10→180/tick via `conn.ping(reconnect=True)` at every idle
point + parallelized paywall/body HTTP + `CLASSIFY_BUDGET_SECONDS` 90→240.
Demand-driven top-up (PR #120/#121) added `classify_pending --triggered-only`
(every-1-min cron, gated on a fresh `logs/classify_topup.signal`), page
size 30→40, and the feed touching the signal when the classified buffer
drops below 400.

**Code review (this session) — defenses that are intact:**
- `detect_paywall` / `extract_body` both use bounded connect+read
  timeouts `(min(5,t), t)`, so a single hung host can't block a worker
  indefinitely; the `ThreadPoolExecutor` fan-out therefore drains.
- `job_lock` is `fcntl.flock(LOCK_EX|LOCK_NB)` — released by the OS when
  the process exits (even on crash), so a *crashed* run cannot wedge the
  lock. Only a *live-hung* process could.
- `_run()` pings reconnect at the top of each batch loop and again before
  the write block; `_reclassify_nollm` pings before its SELECT and write.
- `signal_is_fresh` ignores a stale signal (mtime older than
  `CLASSIFY_TOPUP_SIGNAL_MAX_AGE`, default 600s) so a lock held all night
  can't cause a stampede when released.

**Leading hypotheses (ranked), to confirm with prod telemetry:**
1. **The every-1-min `--triggered-only` cron was never installed.** It is
   still an *Open* item in `manual-actions.md` (2026-05-22). If absent,
   demand-driven top-up never fires and only the `*/5` safety net drives
   classification — which, under active reading, empties the buffer
   between ticks and *looks* like a re-stall. **Cheapest to check first.**
2. **Pending supply exhausted upstream.** If `fetch_feeds` is not
   producing new `status='pending'` rows (dead feeds, a fetch crash, or
   genuinely quiet feeds), classification has nothing to do — a supply
   stall masquerading as a classify stall. `should_trigger` also returns
   False when `pending<=0`, so the signal stops firing.
3. **Anthropic credits / key.** Exhausted credits → `LLMUnavailable` →
   rows still mark `classified` via the `-nollm` fallback (rate does NOT
   stall, quality degrades) — but the *shared* balance also stalls the
   agent fleet, a useful corroborating signal.
4. **Live-hung run holding the lock** (e.g. a pathological trafilatura
   parse — the CPU parse itself is not wallclock-bounded, only the HTTP
   fetch is). Would show as a long-lived `classify_pending` process and an
   old `logs/classify_pending.lock`; every tick logs "lock held … skipping."
5. **MySQL-gone-away recurrence** — would show as PyMySQL `(2006)`
   tracebacks in `logs/cron.log`.

**Diagnostic commands (prod):**
```sql
-- supply vs. classified pool (hypothesis 1 & 2)
SELECT status, COUNT(*) FROM articles GROUP BY status;
SELECT MAX(classified_at) FROM article_features;   -- last successful write
SELECT MAX(fetched_at) FROM articles;              -- last fetch
```
```bash
tail -200 ~/public_html/sauce.ai/news/logs/cron.log | grep -E "classify_pending|fetch_feeds"
crontab -l | grep classify_pending          # is the */1 --triggered-only line present?
ls -la ~/public_html/sauce.ai/news/logs/classify_pending.lock
ps aux | grep classify_pending | grep -v grep   # any long-lived run?
```
Admin: `/admin/cron-health` (cron.log tail) and `/admin/usage-summary`
(signal counts) corroborate from the browser.

**Confirmed root cause (2026-05-27, prod `cron.log` review):** hypothesis 1.
The classifier is healthy — every `*/5` tick logs
`classified=200 llm_articles=200 reclassified=0 cost_usd≈0.15`, all
Anthropic calls 200 OK, no PyMySQL `(2006)`, no `lock held … skipping`,
no `LLMUnavailable`. But the every-1-minute `--triggered-only` cron was
**never installed on prod** (it was still an Open item in
`manual-actions.md`): across 4+ hours of log there is not one
`--triggered-only: no fresh signal, exiting` line nor any triggered run,
which is impossible if the cron existed (it logs at INFO every minute).
So PR #121's demand-driven top-up was inert and classification ran only
on the `*/5` safety net, pinned at the `CLASSIFY_BATCH_LIMIT=200` default
(it hits 200 and breaks every tick) → a hard ~2,400 articles/hour
ceiling. With the catalog now at 1,919 feeds and bursty inflow
(`fresh=276`, `fresh=153` ticks observed), the pending backlog wasn't
draining — which presented as "stalled again."

Neither `CLASSIFY_BATCH_LIMIT` nor `CLASSIFY_BUDGET_SECONDS` is set in the
cPanel env, so prod runs the `config.py` defaults (200 / 240s) — confirmed
by the steady `classified=200` cadence.

**Fix:**
- **(A, applied 2026-05-27)** User installed the every-1-minute
  `classify_pending --triggered-only` cron line from `manual-actions.md`,
  re-enabling demand-driven top-up. `job_lock` serializes all classify
  runs, so this fills the idle gaps between `*/5` ticks (each tick runs
  ~165–210s of the 300s interval) rather than running concurrently.
- **(B, optional throughput lever — not yet applied)** Add
  `CLASSIFY_BATCH_LIMIT` (e.g. 300) as a cPanel env var + restart so each
  `*/5` tick uses its full 240s budget instead of stopping at 200. Going
  much higher also needs `CLASSIFY_BUDGET_SECONDS` raised, which risks a
  run bleeding past the 5-min cron interval (the lock then no-ops the next
  `*/5` tick — acceptable). Hold pending observation of whether (A) drains
  the backlog on its own.

**Status note:** root cause identified and fix (A) applied; leaving `open`
until prod telemetry confirms the backlog drains. (2026-05-31: owner
re-confirmed the every-1-min `--triggered-only` cron is installed on prod;
`manual-actions.md` entry moved to Completed. Still `open` pending the
backlog-drain observation.)

---

## In progress

### BUG-027 — Article pinned to top of feed regardless of downvote; downvote doesn't remove it
**Status:** in-progress (fix written, PR pending) · **Reporter:** user · **Opened:** 2026-05-26
**Note:** renumbered from BUG-026 → BUG-027 on 2026-05-26 to resolve a
parallel-session BUG-ID collision (a separate session used BUG-025 for the
duplicate-profiles bug, now BUG-026). See `new-engineering-session-instructions.md` §7.4.

User reports a specific article (Dark Reading — "[Virtual Event]
Anatomy of a Data Breach: What to Do if it Happens to You", category
tech) is **always first** in the `/` feed even after downvoting it,
and expects a downvoted article to **disappear** from the feed.

**Two distinct issues, likely:**

1. **"Always first" — probable future-date ranking bug.** The card is
   dated **Jun 18, 15:00** — a *future* `published_at` relative to
   today (2026-05-26). The ranking applies a multiplicative recency
   gate `score = quality * EXP(-recency_w * hours / 24)` (BUG-011). A
   future `published_at` makes `hours` negative, so the exponent is
   positive and the multiplier is **> 1** — i.e. future-dated articles
   get an unbounded recency *boost* instead of decay, pinning them to
   the top. Root cause to confirm: where does the future date come from
   (feed `<published>` parsed wrong / publisher lookahead / `updated`
   vs `published`?) and the ranking should clamp future timestamps so
   `hours >= 0` (recency multiplier capped at 1.0 at "now").

2. **Downvote does not hide the article.** Current thumbs-down
   (`user_signals` / `user_source_prefs`) semantics downweight a
   *source*, not hard-filter an individual downvoted article. User
   expectation here is: a downvoted article disappears. Need to
   confirm current behavior in `routes/signal.py` + how `feed.py`
   consumes signals, then decide: hard-filter downvoted article_ids
   from the feed query (matches the stated expectation) vs. the
   existing downweight model.

**Repro (user):** load `/`, the Dark Reading data-breach article is
first; click the downvote (▼); reload — still first.

**Root cause confirmed:**
1. **Always-first:** `ranking.py` recency gate is
   `EXP(-recency_w * TIMESTAMPDIFF(MINUTE, a.published_at, UTC_TIMESTAMP()) / 1440)`.
   The Dark Reading card is a future-dated "Virtual Event" (Jun 18), so
   `TIMESTAMPDIFF` is **negative** → exponent positive → multiplier
   **> 1**, an unbounded recency *boost*. (The future date is legitimate
   publisher data for an event listing — not a fetch bug — so the fix is
   in ranking, not ingestion.)
2. **Downvote doesn't remove it:** `routes/signals.py` records
   `thumb_down` (and prompts to mute the *source* after 3 downvotes in
   30 days), but `routes/feed.py` only reads `thumb_down` to highlight
   the ▼ button — it never filters the downvoted article out of the
   feed query.

**Fix (PR pending):**
1. `app/ranking.py` — clamp the age at 0:
   `GREATEST(TIMESTAMPDIFF(MINUTE, a.published_at, UTC_TIMESTAMP()), 0)`,
   so a future date caps the recency multiplier at 1.0 ("now") instead
   of boosting. Code-tab Python equivalent clamped to
   `max(article.hours_old, 0)` for parity. New regression test
   `test_recency_clamps_future_dates` (pure, passes in sandbox).
2. `app/routes/feed.py` — for signed-in users, exclude downvoted
   articles from the `/` feed:
   `AND a.id NOT IN (SELECT article_id FROM user_signals
   WHERE user_id = %(_dv_uid)s AND signal_type = 'thumb_down')`. A
   downvoted article now disappears on the next load (matches the user's
   stated expectation). Scope: `/` only; firehose/search/saved/digest
   unchanged. The existing source-mute prompt after repeated downvotes
   is preserved.

**Verification:** ranking clamp unit-tested in sandbox. The feed
downvote-filter is route+DB level — deferred to CI / a real env (same
sandbox limitation as prior feed-route changes). No DB migration, no
cron, no env var.

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

### BUG-028 — "Why?" ranking explainer 500s on every click
**Status:** resolved · **Reporter:** internal (found while building "Tune
from this article") · **Opened:** 2026-05-31 · **Closed:** 2026-05-31 (PR pending)

The "Why this ranked" popover (feed card → `GET /article/<id>/explain`,
PR #79) raised `AttributeError` and 500'd on every open. Root cause: a
silent signature drift. `feed._active_weights()` was later changed to
return a `(weights, active_algo_id)` **tuple** (when the per-algorithm
keyword feature, ~PR #82 / 2026-05-20, needed the active id), and
`feed.index()` was updated to unpack it (`weights, active_algo_id = ...`)
— but the older `explain()` route still did `weights = _active_weights()`
and passed the **tuple** to `explain_article(row, weights, ...)`, which
calls `weights.get(fk)`. A tuple has no `.get`, so every Why click threw.
The pure `app/explain.py` tests never caught it because they call
`explain_article` directly with a dict; the route itself had no test.

**Fix:** unpack the tuple in the route — `weights, _ = _active_weights()`
(`app/routes/feed.py`). One line. Caught while reusing the same
active-weights resolution for the new Tune endpoints. **Lesson:** a helper
that changes its return shape needs every caller updated in the same
change; a route with no test can drift silently for ~11 days.

---

### BUG-026 — Algorithm switcher dropdown on `/` lists duplicate profiles
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-26 · **Closed:** 2026-05-26 (PR pending)
**Note:** renumbered from BUG-025 → BUG-026 on 2026-05-26 to resolve a
parallel-session BUG-ID collision (BUG-025 is the feed-stale / geo-migration
bug anchored by merged PR #135). Original PR/commit text may still say BUG-025.

User reported the front-page "Algorithm:" selector showing the same
algorithm names repeated many times (screenshot: "Lefty" x3,
"Karenizer" x3, "Anti Yellow Media" x3, "Karen Maker" x3, "Fred's News"
x3, "Palo"/"Non Yellow"/"general"/"Heady" x2 each), interleaved with the
one-per-profile entries plus "Default"/"Custom".

**Root cause:** not a query fan-out or a template bug — the switcher
faithfully renders the rows in `user_algorithms`. `_switcher_profiles()`
in `app/routes/feed.py` runs a plain `SELECT ... WHERE user_id = %s`
(no JOIN) and `feed.html` renders one `<option>` per row, so every
entry (including "Default"/"Custom", which are just profile *names*) is
a real saved row. The duplicates are genuinely-duplicate rows that
accumulate because two write paths `INSERT` a new profile with no
guardrail: `gallery.adopt()` (`app/routes/gallery.py`) clones a fresh
row on every "Adopt as my feed" click, and `algo.create_profile()`
(`app/routes/algo.py`) saves a new row even when the name already
exists. `save`, `use_preset`, and `onboarding` correctly
update-in-place / are idempotent and were not implicated.

**Fix (PR pending):** prevent + de-dupe display (per owner's choice).
1. **Prevent** — `create_profile()` and `gallery.adopt()` now look up an
   existing same-named profile for the user first; if found they
   **update that row's weights** (adopt also refreshes its keywords:
   wipe-then-reinsert `algorithm_term_prefs`) and re-activate it instead
   of inserting a duplicate. New names still insert as before.
2. **De-dupe display** — new pure helper
   `feed._dedupe_switcher_rows(rows)` collapses duplicate-named rows so
   each name appears once in the dropdown. Rows arrive ordered
   `is_active DESC, updated_at DESC`, so the kept row for a name is the
   active one (if active) else the most-recent; the active id is computed
   from the full set so the `<option selected>` always resolves. This
   also tidies the *pre-existing* duplicate rows already on prod (they
   stay in the DB, non-destructive, but stop showing repeated).

**Scope:** app-layer only — no DB migration, no schema/cron/env/dep
change. Pre-existing duplicate rows are not deleted (the owner chose
non-destructive); they simply collapse in the UI and stop multiplying.

**Verification:** 20 new/updated unit tests
(`test_feed_switcher.py` pure de-dupe; `test_algo_profiles.py`
create-reuse; `test_gallery_adopt.py` adopt-reuse + keyword refresh);
full suite 563 passed. Browser verification on prod deferred (sandbox
has no browser — same documented limitation as PR #53/#59/#72).

---

### BUG-025 — Feed stale: no new articles since May 20; refresh and algo changes show the same articles
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-26 · **Closed:** 2026-05-26

User reported the `/` feed frozen at May 20: reloading and switching
the active algorithm both returned the same articles.

**Root cause:** classic **BUG-007 class**, on the cron write path.
`fetch_feeds` was healthy (new articles kept arriving as
`status='pending'`), but `classify_pending` crashed on **every** tick
at the `INSERT INTO article_features` (classify_pending.py:428):

```
pymysql.err.OperationalError: (1054, "Unknown column 'geo_lat' in 'INSERT INTO'")
```

The geo / "Near a place" feature merged with migration
`news/seed/migrations/2026-05-20-geo.sql` (adds `geo_lat`, `geo_lng`,
`geo_place` + `idx_feat_geo` to `article_features`), wired into
`schema.sql` and the `classify_pending` INSERT — **but the migration
was never applied on prod and was never tracked in `manual-actions.md`**
(the gap that let it slip past the BUG-007 discipline). Because the
feed only shows `status='classified'` rows, the classified corpus
froze at the last good tick (~May 20) while `pending` silently piled
up to ~57k rows. *(A parallel session independently filed this same
issue from the `/admin` Overview — 56,604 pending / 0 classified by
LLM today / $0 spend today vs $18.88 over 30d / 2,451 fetched today /
706 of 1,930 feeds errored — which corroborates: fetch healthy,
classify making zero progress. That duplicate BUG-025 was folded into
this entry.)* The "same articles on refresh / algo change"
sub-symptom was the expected downstream effect of a frozen corpus
(every algorithm drew from the same stale pool; multiplicative
recency decay can't differentiate when everything is equally old) —
not a separate ranking regression. Unrelated to the QA-filed
BUG-023/024 (a web-tier/Cloudflare matter; the user's browser loaded
the site fine throughout).

**Fix:** applied the missing migration on prod via phpMyAdmin
(`lt1ih6uyy2z6_news`) — see `manual-actions.md` Completed
2026-05-26. No code change: the repo already matched; the defect was
purely the unapplied migration. `classify_pending` is a fresh process
each cron tick, so it recovered on the very next tick with no restart
— verified live: ~13 consecutive successful Anthropic classify calls
with zero tracebacks after the ALTER, and the user confirmed the feed
freshening. The ~57k `pending` backlog drains **oldest-first**
(`ORDER BY fetched_at ASC`, classify_pending.py:287) at ~180/tick
(~50k/day), so the feed's newest date advances day-by-day over ~a day
rather than jumping straight to today — self-healing, no action
needed.

**Process learning (same as BUG-007):** a load-bearing migration
shipped without a `manual-actions.md` Open entry to gate it. The
crash was on the cron write path rather than a user route, so it
failed *silently* (no user-visible 500 — the site stayed up serving
the stale corpus), which is why it went unnoticed for 6 days. Every
`news/seed/migrations/*.sql` that adds a column written by a cron job
must get an Open `manual-actions.md` entry the moment it merges.

### BUG-022 — Topnav text overflows page width
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-20 · **Closed:** 2026-05-20 (PR pending)

User reported the topnav extended past the width of the main page.

**Root cause (`app/static/style.css` `.topnav`):** the nav had a
full-size (`1em`) font with `1.2em` gaps and no `flex-wrap` on
desktop. Signed-in users have ~10 link items (Feed, Trending,
Firehose, Gallery, Your Algo, Your Sources, Saved, Your Keywords,
Settings, plus Admin for admins, plus Sign-out-with-email-address)
flanking a 14em search box and trailing Compact/Dark toggles. The
accumulated width exceeded a typical desktop viewport, and without
`flex-wrap` the row ran off the right edge instead of wrapping. The
existing `@media (max-width:640px)` block added wrap and a tighter
font-size only on mobile.

**Fix (PR pending):** in `.topnav`, reduce `font-size` to `0.88em`,
tighten `gap` from `1.2em` → `0.9em`, and add `flex-wrap: wrap` so
the row falls to a second line on overflow instead of running off-
screen. Brand `font-size` bumped from `1.05em` → `1.15em` (and its
`margin-right` tightened) so the wordmark stays a touch larger than
the link row — net absolute size of the brand is roughly unchanged.
Mobile media-query rules still win below 640px (they override
`font-size` and `gap` for that breakpoint).

**Scope:** CSS-only, single rule + one selector tweak. No template,
DB, cron, env, or pip change. Picked up on the next Python App
restart (Jinja autoreloads templates; CSS is statically served).

### BUG-021 — Feed dominated by a single source across multiple algorithms
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-20 · **Closed:** 2026-05-20 (PR pending)

User reported the `/` feed was filled with Philadelphia Inquirer
articles under different algorithms — described as a "weird recency
bias". The same source crowded out the catalog regardless of which
algorithm was active.

**Root cause (`app/routes/feed.py` `index()`):** the feed query had no
per-source diversification at all. It ordered by `score DESC` (or
`published_at`/`f.trending` depending on `?sort=`) and took the top 30.
Dedup is per-`story_id` (cluster), not per-source — so a source with a
recent fetch burst, or with high `source_reputation` plus the
multiplicative recency gate (BUG-011 fix) hitting many of its rows at
once, legitimately rose into 30 of the 30 slots until ~24h decay
broke it up. Score jitter (BUG-012 fix) shuffled within a tier but
didn't cap any source.

**Fix (PR pending):** new pure `app/feed_diversify.py` (Flask-free /
DB-free, mirrors `app/spectrum.py` / `app/firehose_cursor.py`):
`cap_per_source(rows, cap=N, key="source_id")` keeps at most N rows per
source while preserving input order; `fetch_budget(page, page_size,
cap)` returns the SQL row budget needed to guarantee a full page after
capping; `page_slice` returns the requested window of the capped list.
`feed.index()` now over-fetches `page * page_size * multiplier` rows
from MySQL, applies the cap, then slices the requested page —
pagination is stable across pages because page N+1 sees the same
capped sequence as page N. New `FEED_MAX_PER_SOURCE` config (default 3,
env-tunable; 0 disables the cap). Only the `/` route is touched —
`/firehose` (deliberately un-deduped), `/search`, `/saved`, and the
email digest are unaffected.

**Scope decision:** Python-layer cap rather than a SQL window function
(`ROW_NUMBER() OVER (PARTITION BY source_id)`) so the fix is
version-agnostic across the shared MySQL / MariaDB host fleet and
unit-testable without a DB. 14 pure tests in
`tests/test_feed_diversify.py` cover the cap, the over-fetch budget,
page-slice stability across pages, and a "50-row same-source burst"
regression case. No DB migration, no cron, no env required.

### BUG-020 — Firehose view doesn't show all articles
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #72, draft)

User reported the `/firehose` view "doesn't actually show everything" —
articles that should be in the live stream were missing.

**Root cause (`app/routes/firehose.py` `stream()` + `templates/
firehose.html`):** the firehose was a *refreshing snapshot*, not a
stream. It polled `/stream` every 4s with `hx-swap="innerHTML"`, so each
tick **replaced** the whole table with only the newest ≤25 classified
rows (`LIMIT` default 25, no "Load more"; the route's `since` cursor was
never sent by the template). Anything past the newest 25 was dropped on
every poll. (The `WHERE a.status='classified'` gate also hides
not-yet-classified rows — that is the by-design "as they're classified"
behavior the page advertises and was explicitly out of scope per the
user's "make it accumulate" choice; this fix keeps classified-only.)

**Fix (PR #72):** the page now *accumulates*. A stable
`<tbody id="firehose-rows">` is rendered once; the 4s poll prepends only
rows newer than the current top (`hx-swap="afterbegin"`) and a "Load
more" button appends older rows (`hx-swap="beforeend"`), so nothing is
discarded. Pagination is a **keyset on `(classified_at, id)`**, not a
timestamp-only cursor: `classified_at` is second-granularity and
`classify_pending` writes same-second bursts, so a timestamp-only cursor
would skip rows on the boundary second (the actual data-loss mechanism).
The keyset clause is built by a new pure `app/firehose_cursor.py`
(Flask/DB-free, mirrors `app/trending.py`/`app/profiles.py`); 9
sandbox-run unit tests in `tests/test_firehose_cursor.py` (incl.
malformed-id → no-cursor, so a bad client request can't 500 the stream).
Reuses the existing `.load-more` CSS class — no `style.css` change.

**Verification:** pure-helper logic 9/9 green in-sandbox; templates
Jinja-parse, changed Python `py_compile` clean. Route- and browser-level
behavior (live prepend, Load-more append, pause/resume) deferred to a
real env / CI — the sandbox has no Flask/PyMySQL/browser (same
documented limitation as PR #53/#59).

**Known minor caveats (acceptable for v1):** (a) the live-tail poll
fetches up to `limit=100` newer rows per 4s tick; a burst of >100
classifications inside a single 4s window would leave a gap until "Load
more" — not reachable at the real `classify_pending` write rate
(~180/tick spread over the cron wallclock budget, well under 100/4s).
(b) If a row is later *reclassified* (its `classified_at` moves forward,
e.g. PR #56's `_reclassify_nollm`) it can re-appear at the top while its
old position remains — a duplicate, not a loss.

### BUG-019 — LLM-fallback classifications are permanent and unmarked
**Status:** resolved · **Reporter:** internal (classifier review) · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #56)

On `LLMUnavailable` (missing key, Anthropic 5xx/timeout) `classify_pending`
fell back to `political_lean = source_lean`, `objectivity = 0.5`, marked the
row `classified` with `classifier_version='v1'`, and never revisited it (the
work query is `WHERE status='pending'`). Any outage window permanently
contaminated the two flagship LLM features with no marker and no re-classify
path.

**Fix (PR #56):** new pure helper `_classifier_version()` tags fallback rows
with `<CLASSIFIER_VERSION>-nollm` so they're queryable, and a new bounded
`_reclassify_nollm()` pass re-runs the LLM over those rows (oldest first,
one `LLM_BATCH_SIZE` per tick) only when the pending queue is drained and
wallclock budget remains, rewriting `classifier_version` back to the clean
base on success. A persistent outage just leaves rows tagged for the next
tick (no infinite cost). Unit-tested in `tests/test_classify_pending.py`.

### BUG-018 — `simhash == 0` collapses unrelated articles into one megacluster
**Status:** resolved · **Reporter:** internal (classifier review) · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #56)

`rules.simhash64` returns `0` for empty/all-stopword token sets; `fetch_feeds`
inserted that 0. `classify_pending._assign_story_id` filtered
`a2.simhash IS NOT NULL` but not `<> 0`, and treated `my_sim == 0` as valid
(`my_sim is not None`). Every zero-simhash article was Hamming-distance 0
from every other, so they all merged into one cross-topic "story"; the feed
shows only the canonical, so the rest silently vanished from the deduped
feed.

**Fix (PR #56):** `_assign_story_id` now skips the simhash branch when
`my_sim` is falsy (`if not candidate and my_sim:`) and the candidate query
excludes `a2.simhash = 0` (`AND a2.simhash <> 0`); `fetch_feeds` stores
`NULL` instead of `0` (`article_simhash(...) or None`). Existing 0 rows are
harmless once the consumer ignores them. Covered by new
`tests/test_assign_story_id.py` cases.

### BUG-017 — `journalist_reputation` penalizes any article with a parseable byline
**Status:** resolved · **Reporter:** internal (classifier review) · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #56)

`rules.py` seeds `journalist_reputation = source_reputation` (~0.6). Nightly
`maintenance.py` overwrote it for bylined articles with
`0.5*avg(source_reputation) + 0.5*tenure`, where tenure derived from
`journalists.first_seen_at` defaulting to row-creation time. Every journalist
was therefore "new" → tenure≈0 → reputation≈0.3, *below* the no-byline
fallback of ~0.6. With catalog `default_weight 0.6`, a recognized byline cost
an article ~0.18 quality vs. an identical byline-less one — a perverse,
systematic bias persisting ~a year.

**Fix (PR #56):** `_ensure_journalist()` now seeds `journalists.first_seen_at`
from the article's `published_at` (and pulls it earlier for an existing
journalist if this article predates it). The `maintenance.py` reputation
recompute is floored at the journalist's average source reputation —
`GREATEST(avg_rep, 0.5*avg_rep + 0.5*tenure)` with `tenure` clamped
non-negative — so tenure is upside-only and a byline can never score below
the no-byline fallback. `_ensure_journalist` behavior unit-tested.

### BUG-016 — Popularity feature chronically under-counts (signal lost while pending)
**Status:** resolved · **Reporter:** internal (classifier review) · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #56)

`classify_pending` wrote `article_features.popularity = 0.0` on the first
INSERT and (correctly) omitted `popularity` from its `ON DUPLICATE KEY
UPDATE`. `popularity_poll` only `UPDATE`s `article_features` rows that
already exist, so anything that trended on HN/Reddit while still `pending`
(the normal case — articles trend within hours, classify runs in batches)
lost its signal permanently; nothing reconciled `article_features.popularity`
back from `popularity_signals`.

**Fix (PR #56):** single shared `app.classifier.popularity_score()` helper
(popularity_poll's `_popularity_score` now delegates to it). `classify_pending`
seeds `popularity` from existing `popularity_signals` rows at classify time
instead of writing 0.0, and `maintenance.py` runs a nightly authoritative
reconciliation recomputing `article_features.popularity` from
`popularity_signals` using the same log curve in SQL (idempotent, 7-day
window). Formula parity unit-tested against the cron wrapper.

### BUG-015 — Popularity sort surfaces almost exclusively Hacker News
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #53)

Sorting the feed by Popularity (`?sort=popularity`, added PR #48)
returned a feed dominated by Hacker News links.

**Root cause:** the sort was `ORDER BY f.popularity DESC`, where
`article_features.popularity` is written *only* by `popularity_poll`
matching article URLs against Reddit + HN. Per INSTALL.txt §8F that
matches ~5-10% of articles, so the vast majority have `popularity=0`
and the small non-zero set skews HN-heavy. The sort therefore
collapsed into "the handful of links that hit HN" and discarded the
user's algorithm entirely.

**Fix (PR #53):** added an *external trending* signal independent of
the Reddit/HN URL match.

- New `app/trending.py` (pure, Flask-free): parses Google Trends
  daily-trends RSS + Google News RSS (top stories + a few topic
  sections) into weighted topics (token bag + 0..1 heat), and scores
  an article by the fraction of a hot topic's vocabulary it contains
  scaled by that topic's heat.
- New `jobs/trending_poll.py` cron (every 30 min, `job_lock`,
  ping-reconnect before writes per BUG-009). Recomputes
  `article_features.trending` over the rolling `TRENDING_WINDOW_DAYS`
  (default 2) window each tick, so stale topics decay out with no
  separate reset job.
- New `article_features.trending FLOAT` column + `trending` entry in
  the `FEATURES` catalog / `feature_catalog` (opt-in, default weight 0
  — existing user algorithms are unchanged).
- The feed's `popularity` sort is renamed **Trending** and is now
  `ORDER BY f.trending DESC, score DESC`: trending heat first, the
  user's algo score as the within-trending tiebreak — relevance is
  preserved, the feed is just re-ordered toward what's trending.
  Legacy `?sort=popularity` is aliased to `trending` so old bookmarks
  / digest links don't fall back to relevance.

**Known limitation (documented INSTALL.txt §10):** matching is
token-overlap, not entity/synonym aware — "Fed" won't match the
"federal reserve" trend. Good enough for v1; improves when entity
extraction lands (roadmap: Trending topics view / Signal Learning).

**Note on numbering:** PR #50 (merged) landed BUG-013 and BUG-014
first, so this is numbered BUG-015 (same convention as the
BUG-010→BUG-011 renumber).


### BUG-014 — `ModuleNotFoundError: No module named 'langdetect'`
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #50)

User hit `ModuleNotFoundError: No module named 'langdetect'` after the
first BUG-013 commit added `langdetect==1.0.9` to `requirements.txt`.

**Root cause:** langdetect 1.0.9 is sdist-only (no wheel) and its old
`setup.py` fails to build under modern PEP 517 / setuptools — `pip
install -r requirements.txt` errors with `Failed building wheel for
langdetect`, so the package never installs and the import then fails.
Reproduced locally. Same operational class as the feedparser/sgmllib3k
build note in INSTALL.txt §2c. Runtime path was already safe
(`_detect_lang_probs` lazy-imports inside `except Exception` → missing
package degrades to permissive accept, never a crash); the error was
purely install-time / the verify step.

**Fix (PR #50):** swapped the dependency to `py3langid==0.3.0`, which
ships a prebuilt wheel (and pulls `numpy>=2.0.0`, also wheel-distributed
manylinux cp311) — `pip install` is now a plain download with no build
step, so this failure class cannot recur. `app/language.py` stage 3
now uses `py3langid`'s `LanguageIdentifier` with `norm_probs=True` and
`rank()`; the conservative guard (≥24 Latin letters, `top_prob >=
0.85` AND `english_prob < 0.10`) is unchanged. py3langid is
deterministic so no seeding is needed. Verified end-to-end against the
real library: German/Spanish/Finnish rejected, English (incl. short
and accented) kept. 30/30 `test_language.py` green (detector stubbed
via `sys.modules` so the suite stays deterministic and install-free).

### BUG-013 — Non-English articles still appearing in the feed
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-17 · **Closed:** 2026-05-17 (PR #50)

User reported still seeing fresh non-English articles — German,
Spanish, and Finnish (the reported hs.fi link is a Finnish sports
headline) — despite the English-only fetch-time filter from PR #42.

**Root cause:** not a defect — the documented v1 limitation of
`app/language.py`. The filter's two stages were (1) trust a
non-English RSS `<language>` tag, (2) reject on >25% non-Latin letter
ratio. German/Spanish/Finnish are Latin-script, so stage 2's ratio is
≈ 0 and they pass; the offending feeds also don't self-declare a
non-English tag, so stage 1 misses them. Heuristic could not
distinguish English from other Latin-script languages.

**Fix (PR #50):** added a third stage to `is_english` — a language
detector on the surviving Latin-script text when it has ≥24 Latin
letters. Rejects only on a confident non-English call with English an
unlikely alternative (`top_prob >= 0.85` AND `english_prob < 0.10`),
biased toward keeping English so short/edge headlines aren't
over-filtered. Detector is lazy-imported and every failure path
(raise, degenerate input, package absent) falls through to accept —
the fetch loop never breaks. Detector dependency is `py3langid==0.3.0`
(see BUG-014 — the initially-chosen `langdetect` wouldn't build on
prod). 9 new unit tests (30 total in `test_language.py`, all green);
the detector is stubbed via `sys.modules` so the suite is
deterministic.

**Prod note:** verified by unit tests and end-to-end against the real
py3langid. The prod `pip install -r requirements.txt` (py3langid +
numpy) was applied 2026-05-17 (user-confirmed; manual-actions.md
Completed), so the stage-3 filter is now live on `fetch_feeds`. The
import fails soft so this was never a site-down risk. Pre-existing
non-English rows are not purged; they age out of the 7-day window
(BUG-011 recency gate crushes them well before that).

### BUG-012 — Refreshing the feed page returns the same content
**Status:** resolved · **Reporter:** user · **Opened:** 2026-05-13 · **Closed:** 2026-05-13

With the multiplicative recency gate from BUG-011 the feed was fresh
in absolute terms, but ranking was fully deterministic — the same
top-N articles rank identically on every reload until either a new
article arrives or enough time passes for recency decay to reshuffle
the top. From the reader's perspective the feed felt static between
visits.

**Root cause:** `app/ranking.py:build_score_sql` produced a pure
arithmetic SQL expression with no random component. With `ORDER BY
score DESC, a.published_at DESC`, identical inputs guarantee
identical outputs. Refreshes inside the multi-second recency-decay
plateau saw zero shuffle.

**Fix (BUG-012, PR #46, merged 2026-05-13):** added an opt-in `jitter` kwarg to
`build_score_sql`. When `jitter > 0` and the score has any active
quality features, the final expression is wrapped in
`* (1 + RAND() * %(jitter)s)`. The live feed route (`/`) now passes
`current_app.config["FEED_JITTER"]` (default 0.10) so consecutive
refreshes shuffle articles within ~10% score bands — peer-rank
articles trade places, but a clearly-better article still beats a
clearly-worse one. The digest job, `/firehose`, and `/algo` preview
keep the default `jitter=0` so their outputs stay deterministic
(digest must be stable per send; firehose orders by
`f.classified_at` anyway; algo preview is a tuning surface where
randomness would just confuse the user). Env-var
`FEED_JITTER=0` disables on prod if it ever causes issues.

**Known caveat:** because jitter is per-query, an article on the
border between page N and page N+1 could appear on both (or neither)
when the user paginates via "Load more". Acceptable for v1 — the
page-1 refresh experience is the primary win, and the JS-level
duplicate-by-id behaviour the template already has prevents a
visible double-render. Per-user seen-recently downrank is the
principled follow-on (now noted on the Signal Learning roadmap
entry).

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

**Recurrence — 2026-05-17 (PR #64, article save / bookmark):** the
`user_saves` migration was logged Open with full inline SQL, but PR
#64 was merged before the user confirmed it ran. The merged code
`SELECT`s `user_saves` on every signed-in feed load and the nightly
`maintenance` job DELETEs against it, so signed-in `/` 500'd (anon
unaffected) for the few-minute gap until the user ran the `CREATE
TABLE` + restarted the Python App; entry then moved to Completed
(same day). Same root cause as the original: the Open load-bearing
entry didn't *gate* the merge. Reinforced learning: when a PR has an
Open load-bearing `manual-actions.md` entry, do not merge it until
the user confirms the migration ran. Recurrence resolved same day;
overall status stays `resolved`.

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
