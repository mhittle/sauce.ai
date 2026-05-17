# sauce.ai/news — Engineering history

Chronological log of architecture decisions, bugs hit, and fixes applied
to sauce.ai/news. This is the **condensed working history** — read it
end-to-end before making changes; it is kept under a ~14K-token budget so
a session can ingest it in a single `Read`.

How this file is structured:

- **Load-bearing production state** (immediately below) is durable. It is
  **never archived**, because it captures server-side state that is not
  in the repo and will reintroduce already-fixed bugs if lost.
- The chronological log keeps the **most recent entries in full**.
- Older entries are compressed into **Condensed history** (one short
  paragraph each). Their full verbatim text — root causes, calibration
  notes, file lists — lives in `engineering-history-archive.md`, which is
  consulted **on demand** when troubleshooting or needing deep context,
  **not** during normal onboarding.
- **Original product spec** is kept at the bottom (also never archived).
- Append a new dated section at the top of the chronological log whenever
  something meaningful happens (see
  `new-engineering-session-instructions.md`). When this file exceeds its
  budget, run the archive procedure in `engineering-session-wrapup.md`.

---

## Load-bearing production state (read before touching prod)

Not in the repo — re-derived here so it survives history condensation.
Also cross-referenced in `bugs.md` (BUG-001/002), `INSTALL.txt` §8/§9,
and `new-engineering-session-instructions.md` Step 10. If these conflict,
this section + `INSTALL.txt` win.

**Host / paths**

- GoDaddy cPanel/CloudLinux. Account `lt1ih6uyy2z6`. App root
  `~/public_html/sauce.ai/news`. venv
  `~/virtualenv/public_html/sauce.ai/news/3.11`. DB `lt1ih6uyy2z6_news`
  (MySQL via PyMySQL). Live at https://sauce.ai/news.
- Secrets live ONLY in cPanel "Setup Python App" env vars (canonical
  source of truth — not in the repo, not in `.env`): DB creds,
  `ANTHROPIC_API_KEY`, optional `SMTP_*`, `FEED_JITTER`, `DISCOVER_*`.

**Load-bearing files / symlinks (recreate if lost)**

- Three symlinks in `~/public_html/sauce.ai/news/`: `activate`,
  `set_env_vars.py`, `python3.11_bin` → the real venv `bin/` files
  (BUG-001). If missing, the CloudLinux venv shim resolves `${CWD}` to
  the app root and Passenger fork-bombs. Recreate:
  ```
  cd ~/public_html/sauce.ai/news
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/activate activate
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/set_env_vars.py set_env_vars.py
  ln -sf ~/virtualenv/public_html/sauce.ai/news/3.11/bin/python3.11_bin python3.11_bin
  ```
- `~/passenger_wsgi.py.working` — backup of the correct wsgi (BUG-002).
  cPanel may re-scaffold a self-recursive `passenger_wsgi.py` on App
  recreate / Python-version change; the repo version is correct, restore
  with `cp`.
- `~/htaccess.working` — backup of the env-vars `.htaccess` (carries the
  DB password + Anthropic key; sensitive even though uncommitted).
- `~/news-db-YYYYMMDD.sql` — DB snapshot taken after the first
  successful run.
- Harmless clutter: `~/public_html/sauce.ai/news/jobs/*.bak-*` (BUG-009
  in-place patch backups, superseded by the merged deploy; safe to
  delete at leisure).

**Hard rules**

- Do NOT set `APPLICATION_ROOT` in cPanel env vars — double-prefix 404s
  every URL (BUG-004).
- Never set `dangerous-clean-slate: true` in
  `.github/workflows/main.yml` — it wipes the symlinks/backups above.
  Incremental sync (`false`) is correct.
- CloudLinux nproc/EP limit is tight (~115). On `fork: Resource
  temporarily unavailable`: Stop the Python App in cPanel first, then
  pkill python, wait 60s.
- pip installs are run from cPanel Terminal inside the venv (the cPanel
  "Run Pip Install" button is greyed out). `trafilatura` was installed
  this way (PR #21).
- After any deploy that changes routes/blueprints/templates, restart the
  Python App in cPanel (Passenger caches imports until restart).

**Cron (in the cPanel crontab, not in the repo)**

`fetch_feeds` 15m · `classify_pending` 5m · `popularity_poll` 30m ·
`maintenance` nightly 03:30 UTC · `send_digest` 12:00 UTC ·
`discover_harvest` hourly :15 · `discover_promote` 04:00 UTC ·
`discover_llm` Mon 05:00 UTC. Each line `source`s the venv `activate`
and appends to `logs/cron.log`; all wrapped in `job_lock` (fcntl) so an
overlapping tick no-ops.

---

## 2026-05-17 — Engineering-history archive process

### Context

`engineering-history.md` had grown to ~34.8K tokens (~85 KB) — past the
25K single-`Read` ceiling — so the onboarding step "read it end-to-end"
could no longer be done in one pass. Introduced a token budget + an
on-demand archive so the working history stays ingestible without losing
historical detail.

### What shipped

- **`engineering-history-archive.md`** (new) — verbatim historical
  record, newest-first, same heading format. Read on demand
  (grep by PR#/BUG-ID/date) when troubleshooting or needing deep
  context; not part of normal onboarding.
- **`engineering-history.md` condensed** from ~85 KB (~34.8K tokens) to
  ~26 KB (~11K tokens).
  Kept the 3 most recent entries in full; everything from the 2026-05-13
  Story dossier (PR #43) back through the 2026-05-12 v1 deploy was moved
  verbatim to the archive and replaced with terse summaries (date,
  title, PR#, what shipped, load-bearing server-state one-liners).
- **New durable "Load-bearing production state" section** at the top,
  consolidating the not-in-repo server state (symlinks,
  `passenger_wsgi` backup, `.htaccess`, DB snapshot, cPanel env vars,
  hard rules, cron) out of the 2026-05-12 v1-deploy entry so it can
  never age out via condensation. "Original product spec" also stays in
  the live file.
- **Process documented** in `engineering-session-wrapup.md` (new
  Step 1b: check size at wrap-up, archive when over ~14K tokens /
  ~34 KB) and cross-referenced in
  `new-engineering-session-instructions.md` (Step 1 + tl;dr) so future
  sessions maintain it.

### Code touched

- `engineering-history.md` — split + condensed; durable Load-bearing
  section added.
- `engineering-history-archive.md` — new.
- `engineering-session-wrapup.md` — new "Archive
  `engineering-history.md`" step + anti-pattern.
- `new-engineering-session-instructions.md` — Step 1 + tl;dr updated for
  the live/archive split.

### Server-side state touched

None. Docs-only — no DB, cron, symlink, env-var, or pip change.

### PRs

- **PR #51** — Engineering-history archive process (merged 2026-05-17).

---

## 2026-05-17 — BUG-013 + BUG-014: Latin-script filter via py3langid

### Context

User reported still seeing non-English articles in the feed —
specifically German, Spanish, and Finnish (the hs.fi report was a
Finnish sports headline), all *fresh* (last day or two). The
English-only filter from PR #42 (`app/language.py`) was working as
designed; this is the limitation it explicitly documented: stages 1
(feed `<language>` tag) and 2 (non-Latin script ratio) cannot tell
English from German/Spanish/Finnish — they all use Latin letters, so
`_non_latin_letter_ratio` ≈ 0 and the article passes. The feeds in
question don't self-declare a non-English tag, so stage 1 misses them
too.

The first cut shipped `langdetect==1.0.9` (user's chosen approach over
a zero-dep heuristic or a per-source language column). That triggered
**BUG-014**: langdetect 1.0.9 is sdist-only and its old setup.py
fails to build under modern PEP 517/setuptools — `pip install` errors
with `Failed building wheel for langdetect`, so the package never
installs (reproduced locally and on the user's cPanel venv). User
chose to swap to **py3langid**, which ships a prebuilt wheel.

### What shipped

- **`app/language.py`** — added **stage 3** to `is_english`: when text
  survives stages 1+2 and has at least `MIN_DETECT_LETTERS=24` Latin
  letters, run the detector and reject only on a *confident*
  non-English call where English is an unlikely alternative
  (`top_prob >= 0.85` AND `english_prob < 0.10`). Deliberately biased
  toward keeping English — dropping a real English article is a more
  visible regression than an occasional foreign one slipping through.
  `_detect_lang_probs` builds a cached `py3langid` `LanguageIdentifier`
  (`norm_probs=True`) and reads `rank()`; py3langid is deterministic
  so no seeding. Lazy-imported inside a broad `except`: any failure /
  degenerate input / absent package → None → permissive accept, so
  the fetch loop never breaks.
- **`requirements.txt`** — `py3langid==0.3.0` (pulls `numpy>=2.0.0`,
  also wheel-distributed). Replaced the broken `langdetect==1.0.9`.
- **`tests/test_language.py`** — detector stubbed via `sys.modules`
  (fake `py3langid.langid`, same pattern as the trafilatura/anthropic
  stubs) so the suite is deterministic and passes without the package.
  21 → 30 cases: German/Spanish/Finnish rejection, English still
  accepted, short-text skips detector, low-confidence keeps,
  English-plausible keeps, detector-raises and detector-unavailable
  both fall through to accept. Also verified end-to-end against the
  real py3langid.
- **`news/INSTALL.txt` §10** — rewrote the English-filter limitation
  note to describe the three-stage filter, the conservative stage-3
  behavior, and the langdetect→py3langid rationale.

### Why py3langid

User picked langdetect for robustness over a zero-dep word-profile
heuristic; BUG-014 then proved langdetect operationally broken on the
target env (no wheel, fragile setup.py — the recurring install-pain
class this project keeps hitting). py3langid is a maintained
wheel-distributed langid fork: no build step (so BUG-014's failure
class cannot recur), deterministic, normalized 0..1 probabilities via
`rank()`, accurate on the reported samples incl. short headlines.
Still a manual pip-install prod action, but one that actually
installs; and the import fails soft so it is **not** a site-down risk.

### Code touched

- `news/app/language.py` — stage-3 py3langid detection + helpers
  (`_latin_letter_count`, `_detect_lang_probs`), tuning constants
  (`DETECT_MIN_CONFIDENCE`, `DETECT_ENGLISH_FLOOR`).
- `news/requirements.txt` — `py3langid==0.3.0` (was the
  briefly-shipped `langdetect==1.0.9`).
- `news/tests/test_language.py` — sys.modules stub fixture + 9 new
  cases (30 total).
- `news/INSTALL.txt` §10 — updated limitation note.
- `bugs.md` — BUG-013 logged + resolved; BUG-014 logged + resolved.
- `manual-actions.md` — Open entry for the pip install (py3langid).

### Server-side state touched

- **Manual prod action pending**: `pip install -r requirements.txt`
  on cPanel (Terminal, venv activated — the "Run Pip Install" button
  is greyed out) + Python App restart. Tracked in `manual-actions.md`
  with full inline commands and pasted into chat. **Not** a site-down
  risk: the detector import is lazy and fails soft, so the site and
  fetch pipeline keep running; the European-language filtering is just
  inert until py3langid is installed. py3langid + numpy are both
  wheel-distributed so the install is a plain download (no build step
  — this is what fixes BUG-014). No DB migration, no cron change, no
  env var, no symlink.
- The filter is fetch-time only — it does not purge non-English rows
  already in `articles`; those age out of the 7-day window
  (multiplicative recency gate from BUG-011 crushes them well before
  that).

### Tests

`tests/test_language.py` 30/30 pass (stubbed) and verified end-to-end
against the real py3langid (German/Spanish/Finnish rejected; English
incl. short + accented kept). Full local suite: 141 passed of the
runnable set (the sandbox can't build `cryptography`/`requests`/
`dotenv` so 5 collection-erroring + 13 missing-module test files are
environmental, unrelated to this change — confirmed all
`ModuleNotFoundError`).

### PR

- **PR #50** — BUG-013 + BUG-014: py3langid stage-3 for Latin-script
  European filtering (draft).

---

## 2026-05-17 — Techmeme-style discussion links (Reddit/HN)

### Context

User asked for "a feature like what Techmeme does where they list
relevant tweets regarding the article/topic" — i.e. Techmeme's
"Discussion:" line. Literal X/Twitter needs the paid API (~$100/mo,
already flagged on the roadmap social-firehose item); the user picked
**Reddit + HN only** for v1 and **feed card + story dossier** as the
surfaces. This is mostly wiring up data we already fetch:
`popularity_poll` matches Reddit/HN threads to our articles every
30 min for the popularity score but previously discarded the thread
permalink.

### What shipped

- **Schema** — `popularity_signals` gains `permalink VARCHAR(1024)`
  and `subreddit VARCHAR(64)` (NULL for HN). Migration
  `seed/migrations/2026-05-17-discussion-links.sql`. Existing rows get
  NULL permalink and simply render no discussion line until
  `popularity_poll` refreshes them on its next tick.
- **`jobs/popularity_poll.py`** — Reddit posts now capture the full
  thread permalink (`https://www.reddit.com` + `data.permalink`) and
  `data.subreddit`; HN posts capture
  `https://news.ycombinator.com/item?id=<id>`. INSERT/ON DUPLICATE KEY
  UPDATE extended with the two new columns. No behavior change to the
  popularity score itself.
- **`app/discussion.py`** (new) — pure `discussion_label(source,
  subreddit)` ("Hacker News" / "r/<sub>" / "Reddit") plus
  `discussions_for_articles(ids)` (per-article map, comments desc) and
  `discussions_for_story(ids)` (one merged list across a cluster's
  members, deduped by thread URL keeping max comment count). Mirrors
  the Flask-free-helper convention of `discovery.py` / `feed_validation.py`.
- **`app/routes/feed.py`** — after the existing thumb attach, one
  batched `discussions_for_articles` call over the page's article ids;
  `a["discussions"]` rides into both the full and HX "Load more"
  renders.
- **`app/routes/story.py`** — `discussions_for_story` over the cluster
  members, passed to the dossier template.
- **Templates** — `feed_cards.html` gets a compact
  `Discussion: Hacker News (142) · r/technology (89)` line under the
  byline; `story.html` gets a `.dossier-discussion` panel above the
  lean columns. `style.css` gains additive `.discussion` /
  `.dossier-discussion` rules (muted, matches the framing panel
  palette).
- **Tests** — `tests/test_discussion.py` (11 cases): label variants,
  empty-input short-circuits the query, grouping + comments-desc sort,
  missing-id absent, `_merge` dedupe-by-url-keep-max + sort, story
  merge across cluster. `tests/test_story.py` `store` fixture also
  stubs `app.discussion.query` (the route now does one extra DB read).
  Full runnable suite: 177 passing (4 files need
  trafilatura/anthropic/lxml and are environmental, same sandbox
  limit noted on PR #50).

### Code touched

- `news/seed/schema.sql` — two columns on `popularity_signals`.
- `news/seed/migrations/2026-05-17-discussion-links.sql` — new.
- `news/jobs/popularity_poll.py` — capture permalink + subreddit.
- `news/app/discussion.py` — new helper module.
- `news/app/routes/feed.py`, `news/app/routes/story.py` — attach
  discussions.
- `news/app/templates/partials/feed_cards.html`,
  `news/app/templates/story.html`,
  `news/app/static/style.css` — UI.
- `news/tests/test_discussion.py` (new),
  `news/tests/test_story.py` (fixture stub).
- `roadmap.md`, `manual-actions.md` — new entries.

### Server-side state touched

- **Migration pending on prod**:
  `seed/migrations/2026-05-17-discussion-links.sql`. Tracked in
  `manual-actions.md` Open with full inline SQL. **Not a site-down
  risk** — both new columns are nullable and only
  `popularity_poll` writes them / the new read tolerates their
  absence only *after* the ALTER; until the ALTER runs, the
  `popularity_poll` INSERT will error on the new column list, so run
  it before the next 30-min tick. The web routes `SELECT permalink,
  subreddit` so they 500 on the feed/dossier until the columns exist
  — treat as a pre-merge migration like prior schema changes.
- No new cron, env var, dependency, or symlink. Python App restart
  after deploy so the new blueprint code + templates load.

### PR

- **PR #TBD** — Techmeme-style discussion links (draft). Requires the
  one DB migration above before merge.

### Open items

- After the migration + a couple of `popularity_poll` ticks, confirm
  on prod that discussion lines appear on cards whose URLs hit
  Reddit/HN (match rate is the usual ~5-10%, so most cards won't have
  one — that's expected, same as the popularity score).
- Natural follow-ons if the user wants more coverage: free Bluesky
  `searchPosts` harvest (no key, no new dep) feeding the same
  surface; paid X/Twitter is still gated on spend.

---

## 2026-05-14 — Feed sort selector (Relevance / Newest / Popularity)

### Context

User asked for "the same sorts that Google has" on the feed. Google
News parity = a small dropdown with Relevance (algorithmic, default)
and Date. Added Popularity as a third option per the user's
selection — raw `article_features.popularity` (Reddit/HN signal),
useful for an "everyone's reading this" view that ignores the
user's algorithm tuning.

### What shipped

- **`app/routes/feed.py`** — new module constants `SORT_OPTIONS =
  ("relevance", "newest", "popularity")` and `SORT_LABELS`. Two pure
  helpers: `_normalize_sort(value)` (case-insensitive, trims, falls
  back to `relevance` on anything else — including SQL-injection
  attempts) and `_order_by_for_sort(sort)` returning the literal
  ORDER BY clause to inject. Route reads `request.args.get("sort")`,
  normalizes, and substitutes `{order_by_sql}` into the SQL template
  in place of the previous fixed `ORDER BY score DESC,
  a.published_at DESC`. Threshold filters, source-pref weights, and
  visibility filters all still apply — only the ordering changes.
- **`app/templates/feed.html`** — wrapped category tabs in a new
  `.feed-controls` flex row alongside a small `<form method="get">`
  with a `<select name="sort">` that auto-submits on change. Category
  tab `href`s thread `sort=` through `url_for` (omitting it when
  it's `relevance`, so the default URL stays clean: `/`,
  `/?category=tech`, `/?sort=newest`,
  `/?sort=newest&category=tech`).
- **`app/templates/partials/feed_cards.html`** — HTMX "Load more"
  button preserves `sort` the same way.
- **`app/static/style.css`** — single `.feed-controls` /
  `.sort-form` rule block; mobile media block stacks the form below
  the tabs at ≤640px.
- **`tests/test_feed_sort.py`** — 8 cases covering: SORT_OPTIONS
  shape; `_normalize_sort` passes through valid values; falls back
  to `relevance` for None/empty/whitespace/unknown/SQL-injection
  strings; case-insensitive + trim; ORDER BY for each sort puts the
  right column first; popularity ties break on recency (not score);
  unknown value defaults to relevance. Full suite: 190 passing (was
  182).
- Manual render smoke-test via test client: `/`, `/?sort=newest`,
  `/?sort=popularity`, `/?sort=bogus`, `/?sort=newest&category=tech`
  all return 200 with the correct option pre-selected.

### Notes for next session

- Behavior on `newest`: `recency` from the algorithm slider has no
  practical effect on the ORDER BY (we sort by `published_at`
  directly), but it's still computed in the score expression because
  `score DESC` is the tiebreaker. Filter thresholds still apply, so
  a paywall-hating user sorting by newest still won't see paywalled
  articles. That's correct: sort is a re-order, not an opt-out.
- `popularity` ties break on `published_at`, not on score.
  Acceptable — popularity sort is a deliberately algorithm-agnostic
  view.
- Firehose intentionally untouched — it already orders by
  `f.classified_at DESC` and is the see-everything stream.
- `FEED_JITTER` still applies to the score expression, so the page-1
  reload shuffle from BUG-012 keeps working under `relevance`.
  Jitter is wasted CPU on `newest` / `popularity` sorts since
  `score` is only a tiebreaker there; not worth conditionally
  skipping at this scope.
- Possible future polish: persist the last choice per-user (would
  need a `users.feed_sort` column) — explicitly out of scope per
  the user's "URL query param only" choice this session.

### Code touched

- `news/app/routes/feed.py` — sort helpers + route plumbing.
- `news/app/templates/feed.html` — `.feed-controls` row with
  category tabs + sort `<form>`; tabs preserve `sort=`.
- `news/app/templates/partials/feed_cards.html` — Load more button
  preserves `sort=`.
- `news/app/static/style.css` — `.feed-controls` / `.sort-form`
  rules + mobile media block stack.
- `news/tests/test_feed_sort.py` — new, 8 cases.
- `roadmap.md` — new Done entry; at-a-glance row added.

### Server-side state touched

None. No DB migration, no new cron entry, no env-var change, no new
symlink, no new pip dep. Standard Python App restart on deploy so
the new template + route load.

### PR

- **PR #48** — Feed sort selector (merged 2026-05-14).

---

## 2026-05-13 — BUG-012: refresh-shuffle via score jitter

### Context

User reported: "When someone refreshes their page, the content
presented should change as well." With BUG-011's multiplicative
recency gate the feed is fresh in absolute terms, but ranking is
purely arithmetic — `ORDER BY score DESC, a.published_at DESC` over
a deterministic score gives the same top-30 on every reload until
new articles land or recency decay reshuffles. Logged as BUG-012.

### Root cause

`app/ranking.py:build_score_sql` returns a pure SQL arithmetic
expression with no random component. Identical inputs → identical
outputs. Refresh feels static.

### Fix

Opt-in `jitter` kwarg on `build_score_sql(weights, *, jitter=0.0)`.
When `jitter > 0` AND at least one quality feature is weighted, the
final expression is wrapped in `* (1 + RAND() * %(jitter)s)`. Live
feed route (`/`) passes `current_app.config["FEED_JITTER"]`
(default `0.10`) so consecutive refreshes shuffle articles within
~10% score bands. Other callers stay deterministic by default:

- `jobs/send_digest.py` — daily digest must be stable per send.
- `app/routes/firehose.py` — orders by `f.classified_at DESC`, score
  is only there as a per-row tint, jitter wouldn't affect order.
- `app/routes/algo.py` preview — tuning surface where randomness
  would confuse the user.

Env-var `FEED_JITTER=0` disables on prod if needed.

### Known caveat

Jitter is computed per query, so an article on the border between
page N and N+1 could surface on both (or neither) when paginating
via "Load more". Acceptable for v1 — the page-1 refresh experience
is the primary win. A principled per-user "seen-recently downrank"
(impression tracking + N-hour downweight) is now noted under the
Signal Learning roadmap entry as the follow-on.

### Code touched

- `news/app/ranking.py` — `build_score_sql` gains `jitter` kwarg.
- `news/app/config.py` — `FEED_JITTER` default `0.10`.
- `news/app/routes/feed.py` — passes
  `current_app.config["FEED_JITTER"]`.
- `news/tests/test_ranking.py` — 4 new tests
  (`test_jitter_off_by_default`,
  `test_jitter_wraps_score_with_rand_multiplier`,
  `test_jitter_zero_disables_wrap`,
  `test_jitter_skipped_when_no_active_features`). Full suite 182
  passing on this branch.
- `bugs.md` — BUG-012 logged + resolved.
- `roadmap.md` — Signal Learning entry annotated with the
  seen-recently downrank follow-on.

### Server-side state touched

None. No DB change, no migration, no new cron, no new pip dep, no
new symlink. `FEED_JITTER` is an env-var with a working default, so
the default deploy works without touching cPanel env vars. Python
App restart after FTP/CI deploy so the new code loads.

### PR

- **PR #46** (merged 2026-05-13) — Fix BUG-012: refresh-shuffle via
  score jitter.

---

## 2026-05-13 — English-only article filter at fetch time (PR #42)

### Context

User reported non-English articles surfacing in the feed and asked to
restrict to English "for now". The 768-source catalog mixes ~50-100
non-English outlets (FR/DE/JP/HK/ES/NL/IT/KR plus unlabeled tail in
the QA/IN buckets); some US-labeled outlets also syndicate occasional
non-English wire content. Filter has to work per-article, not just
per-source.

### What shipped

- **`app/language.py`** — pure-Python `is_english(title, summary,
  feed_language)`. Two-stage: (1) if the RSS feed's `<language>` tag
  declares a non-English code (e.g., `ja`, `de-DE`), trust it and
  reject; (2) otherwise count letter characters in title+summary and
  reject if the share outside the Latin script ranges (Basic Latin,
  Latin-1, Latin Extended-A/B, Latin Extended Additional) exceeds
  `NON_LATIN_THRESHOLD=0.25`. Permissive by default — empty/None
  inputs accept. No new dependency.
- **`jobs/fetch_feeds.py`** — filter runs before the
  `INSERT IGNORE INTO articles`. Pulls `parsed.feed.language` once
  per feed, checks each entry's title+summary. Rejected entries
  don't insert and don't bump `fresh`/`stale`; instead a new
  `skipped_lang` counter surfaces in the per-tick summary line
  (`fetched=N fresh=N stale=N errors=N skipped_lang=N`) and in
  `pipeline_log`.
- **Per design call** (user-confirmed): existing non-English rows in
  `articles` are left alone. They age out of the 7-day feed window
  naturally and the multiplicative recency gate from BUG-011
  crushes them within ~4 days regardless of static score. No
  backfill purge.
- **Known limitation, documented in INSTALL.txt §10**: Latin-script
  European content (French, German, Spanish, Italian, Dutch, etc.)
  reads as English by the script heuristic and slips through unless
  the feed self-declares a non-English tag. If those leak in
  meaningful volume, next step is either a curated source-language
  column or adding `langdetect` as a dep.

### Code touched

- `news/app/language.py` — new, pure helpers.
- `news/jobs/fetch_feeds.py` — import + per-entry filter + extended
  `fetch_one` return tuple + summary line includes `skipped_lang`.
- `news/tests/test_language.py` — new, 21 cases covering English /
  CJK / Arabic / Cyrillic / Devanagari / Latin Extended accents /
  Vietnamese diacritics / empty inputs / mistakenly-tagged feeds.
- `news/INSTALL.txt` §10 — v1-limit note.
- `roadmap.md` — new Done entry.

### Server-side state touched

None. No DB migration, no new cron entry, no new pip dep, no env-var
change. `fetch_feeds` is a cron entry — it picks up the new module
on its next tick automatically; no Passenger restart strictly
required. Existing non-English `articles` rows stay in the DB and
age out of the feed window over ~7 days.

### PR

- **PR #42** English-only filter at fetch time (merged).

### Open items

- Watch the next few `fetch_feeds` ticks on prod and confirm
  `skipped_lang` is non-zero in cron.log. Sample a few rejected
  domains to make sure we're not over-filtering legitimate English
  content with heavy named-entity non-Latin (e.g., a US news story
  whose title is "Tokyo's 東京 district reopens" should still pass —
  the 0.25 ratio is tuned for that).
- If French/German/Spanish content is the bulk of remaining
  leakage, follow up with either source-level `language` tagging or
  a `langdetect` dep.

---

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-13

- **Story dossier v1 — `/story/<id>` (PR #43).** Multi-source view of a
  deduped story group across the lean spectrum; new `story_dossiers`
  table caches a Haiku framing summary keyed by member-signature,
  cost-gated to clusters with 3+ members and 2+ lean buckets; "+N
  angles" pill on multi-source feed cards. *Server:* `story_dossiers`
  migration; reuses the existing anthropic dep; restart post-merge.
- **Mobile / responsive polish (PR #40).** Single additive
  `@media (max-width:640px)` block + `.table-scroll` utility in
  `style.css`; desktop layout untouched. *Server:* none (CSS-only).
- **Automated source discovery — Reddit/HN + LLM agent (PR #38).** New
  `candidate_sources` table; 3 cron jobs (`discover_harvest` hourly,
  `discover_promote` nightly 04:00, `discover_llm` weekly Mon 05:00);
  `/admin/discovery` approve/reject/blacklist queue; pure helpers in
  `app/discovery.py`. *Server:* `candidate_sources` migration + the 3
  cron entries; no new pip dep.
- **BUG-011 — multiplicative recency gate (PR #34).** Ranking was
  additive so stale high-quality articles dominated forever; changed
  `recency` to a multiplicative freshness gate
  `score = quality * EXP(-r*h/24)` (`recency=0` = legacy behavior).
  *Server:* none; restart. Full root cause: `bugs.md` BUG-011.
- **BUG-010 — feature bars all rendered identically (PR #35).** Template
  wrote `style="width:NN%"` but `.feature-bars i` is a flex child and
  the CSS reads a `--w` custom property; switched to `style="--w:NN%"`.
  *Server:* none.
- **BUG-008/009 — classify_pending stalled prod (PR #32).** GoDaddy
  shared MySQL drops idle sockets during the long LLM/HTTP gap before
  the write block → added `conn.ping(reconnect=True)` at every idle
  point in `classify_pending` / `popularity_poll` / `fetch_feeds`;
  parallelized paywall + body HTTP via `ThreadPoolExecutor(10)`;
  `CLASSIFY_BUDGET_SECONDS` 90→240; throughput 10→180/tick. Lesson:
  ping-reconnect any cron that does HTTP between writes. *Server:* no
  schema change; `jobs/*.bak-*` on prod are stale (safe to delete).
  Full detail: `bugs.md` BUG-008/009.
- **BUG-007 recovery + wrap-up (PRs #30, #31).** Merged code referenced
  `sources.owner_id` + `user_source_prefs` before those migrations were
  run, 500'ing every reader route; ran them, restarted, drained the
  queue, confirmed prod schema synced, installed trafilatura.
  *Process learning:* treat `manual-actions.md` Open as a load-bearing
  blocker — run a migration before merging the next one. Full detail:
  `bugs.md` BUG-007.
- **Article deduplication across sources (PR #24).** `articles.simhash`
  + `articles.story_id` + `(story_id,published_at)` index; `fetch_feeds`
  computes a 64-bit SimHash and seeds `story_id=id`; `classify_pending`
  `_assign_story_id` clusters via exact `title_hash` or Hamming≤8 over a
  48h window, canonical = highest `source_reputation`; feed dedupes by
  `story_id`, firehose stays un-deduped; `maintenance` heals orphans.
  Heavy paraphrase not clustered (v2 = embeddings). *Server:* dedup
  migration; restart.
- **Manual-actions tracker (PR #22).** Added `manual-actions.md`
  (Open/Completed, full SQL inline) + the session-start/wrap-up
  lifecycle hooks. *Server:* none.
- **User-added RSS feed subscriptions (PR #29).** `/sources` page;
  signed-in users add personal feeds scoped by `sources.owner_id`;
  feed/firehose visibility filter; `app/feed_validation.py`. *Server:*
  `sources.owner_id` migration.
- **In-app reader view + body extraction (PR #21).** `article_bodies`
  table; `app/extractor.py` (lazy `trafilatura`, 1 MB cap,
  `MIN_WORDS=60`) wired into `classify_pending` (paywall-aware, shares
  the cron wallclock budget); `/read/<id>` + reader template; nightly
  `BODY_RETENTION_DAYS` prune. *Server:* `article_bodies` migration +
  `pip install` (trafilatura); restart.
- **Thumbs up/down + signal foundation (PR #19).** Generic
  `user_signals` table (forward-compat for Signal Learning) +
  `user_source_prefs`; `/signal` blueprint (toggle thumbs,
  3-downs-from-source prompt); feed query splices the per-user-source
  weight. *Server:* signals migration.
- **Daily personalized email digest (PR #23).** Opt-in
  `users.digest_enabled` + unsub token; noon-UTC `send_digest` cron
  reusing the feed ranking SQL; stdlib `smtplib` (localhost MTA by
  default; `SMTP_*` env vars for a real relay). *Server:* digest
  migration + the noon-UTC cron; optional `SMTP_*` env vars.
- **Cron hardening + PyMySQL timeouts (PR #15).** `job_lock(name)`
  fcntl mutex in `_bootstrap.py` wrapping each `main()`; `requests`
  timeouts on RSS/Reddit/HN; anthropic `timeout=30`; PyMySQL timeouts
  (web `(5,15,10)`, cron `(5,30,15)`); `FEED_FETCH_BATCH` 80→20.
  *Server:* none; restart; lockfiles appear in `news/logs/`.

### 2026-05-12

- **Paywall feature (PR #14).** Active per-article HTTP probe in
  `classify_pending` writes `article_features.paywall` 0..1 (JSON-LD /
  `content_tier` / phrase heuristics; blocked → 0.5 "suspected");
  opt-in catalog entry; `/admin/feeds` paywall column. *Server:*
  paywall migration.
- **Editorial serif wordmark (PR #13).** `.brand` restyled in
  `base.html` + `style.css` (system serif; italic "news"). *Server:*
  none.
- **Feature batch #7–#11.** #7 fix **BUG-006** (article links: HTMX
  `hx-post` on the anchors → `onclick` fetch+keepalive so browser
  navigation works); #8 category tabs on `/`; #9 3-axis feature config
  (Direction + Weight + Threshold; uniform
  `weight*(1-|v-dir|/scale)`); #10 obscurity features (story + source,
  log-scaled) + migration; #11 source catalog 135→768 +
  auto-deactivate at `error_count=10` + `/admin/feeds` Refresh button.
  *Server:* obscurity migration; +633 seed-CSV import. Detail:
  `bugs.md` BUG-006.
- **Doc framework.** Added `roadmap.md`, `bugs.md` (BUG-001..005
  pre-populated), `engineering-session-wrapup.md`, and wired all into
  `new-engineering-session-instructions.md`. *Server:* none.
- **v1 prototype deploy to GoDaddy (PRs #3, #4).** First working
  deploy. Fixed 5 deploy bugs: `APPLICATION_ROOT` double-prefix 404
  (BUG-004), INSTALL path mismatch (BUG-005), CloudLinux venv-shim
  fork-bomb (BUG-001), cPanel self-recursive `passenger_wsgi.py`
  (BUG-002), `anthropic 0.39` / `httpx 0.28` incompat → bumped to
  `0.101.0` (BUG-003). All not-in-repo server state from this deploy is
  consolidated in **Load-bearing production state** above; root causes
  in `bugs.md` BUG-001..005 and `INSTALL.txt` §8. The Anthropic key +
  DB password were exposed in chat and rotated before close.

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
