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

### BUG-022 — Topnav text overflows page width
**Status:** open · **Reporter:** user · **Opened:** 2026-05-20

User reports the topnav menu has text too large — the nav extends past
the width of the main page (overflows horizontally). Likely cause: the
nav links accumulated past what the current font-size / spacing allows
at typical desktop widths after several recent additions (gallery,
density toggle, dark-mode toggle, search, keywords, etc.).

Repro: load `/` on a desktop browser; observe the topnav links extend
past the main content column / viewport edge.

Fix direction: shrink topnav text and/or tighten spacing in
`app/static/style.css` `.topnav` rules (additive change; no template
restructuring needed). Verify mobile (≤640px) media block still wraps
cleanly.

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
