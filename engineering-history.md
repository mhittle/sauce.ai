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

## 2026-05-17 — Dark mode (PR #62)

Roadmap Pri 3 / LOE 2 (ui). Maintainer-picked. Client-only theme;
no server state, no DB, no manual prod action.

### What shipped

- **`style.css`** — `:root` gains semantic surface vars
  (`--surface`/`--surface-2`/`--surface-3`/`--notice-bg`/
  `--notice-border`/`--err-bg`/`--warn-bg`) with the *current* light
  values, so light mode is byte-for-byte unchanged. A new
  `:root[data-theme="dark"]` block overrides all palette vars (incl.
  brighter `--accent`/`--left`/`--right`/`--ok`/`--warn`/`--err` for
  legibility on dark). ~30 hardcoded literals (`background: white`,
  the `#f0efeb`/`#f7f6f0`/etc. fill family, `#333` lead, `#e3e3df`
  feature-bar track) repointed at the vars — without this the panels
  stayed white on a dark page. `color-scheme` per theme so native
  controls/scrollbars follow. `color: white` on accent buttons left
  literal (correct).
- **`base.html`** — synchronous head script (before the stylesheet
  link) sets `<html data-theme>` from `localStorage.theme`, falling
  back to `prefers-color-scheme` — no FOUC. A `linkbtn`-styled
  `#theme-toggle` button is the last nav item (signed-in or out);
  end-of-body script toggles the attribute, persists to
  `localStorage`, and relabels Dark/Light + `aria-pressed`. Pure
  client-side (no POST) so no CSRF/route/DB involvement.

### Code touched

- `news/app/static/style.css` — theme vars + literal→var repointing.
- `news/app/templates/base.html` — head theme-init, nav toggle,
  toggle wiring.
- `roadmap.md` — Dark mode → in-progress (→ Done on merge).

### Server-side state touched

None. CSS/template only; zero Python. Standard Python App restart on
deploy so the new template/CSS load (Jinja autoreloads templates;
restart is cleaner).

### Verification

- `base.html` Jinja-parses clean; no `.py` touched (suite unaffected;
  sandbox has no pytest/Flask — same documented env limit as PR #50).
- All hardcoded surface literals confirmed mapped (only `color:
  white` on accent + the `:root` var *definitions* remain by design).
- **Not verified**: in-browser toggle/persistence/no-FOUC and the
  dark palette's per-page contrast — deferred to a real env / CI
  (no Flask in sandbox).

### Open items

- Maintainer/CI: load `/`, `/algo`, `/firehose`, `/admin`, `/read`,
  `/story` in dark; toggle; hard-reload (confirm no light flash);
  cross-tab persistence. Tune any dark palette value that reads poorly.
- `engineering-history.md` is at its ~34 KB budget — archive oldest
  entries at the next wrap-up (deliberately not done here to keep this
  low-risk UI PR off the high-conflict archive path).

### PR

- **PR #62** — Dark mode (draft).

---

## 2026-05-17 — Article save / bookmark (roadmap Pri 6)

Roadmap "Article save / bookmark" (Pri 6, LOE 4, new-feature/ui).
Maintainer-picked. Reader view (PR #21 body extraction) is already
live, so the headline value — a **durable personal archive** — is
realizable now; article summaries (a soft pairing) are still backlog
and explicitly out of scope here.

### What shipped

- **Schema** — new `user_saves(user_id, article_id, folder DEFAULT
  'Read Later', saved_at, read_at)` (PK `(user_id, article_id)`, FKs
  cascade). Migration `seed/migrations/2026-05-17-user-saves.sql` +
  `schema.sql`.
- **`app/routes/saves.py`** (new blueprint, no url_prefix; mirrors the
  signals blueprint's INSERT/DELETE+JSON convention). `POST
  /save/<id>` toggles (returns `{saved: bool}`); `POST /save/<id>/read`
  sets `read_at` once (keepalive fetch on click-through); `GET /saved`
  (`login_required`) lists newest-first.
- **Durable archive** — `jobs/maintenance.py` now exempts saved
  articles from BOTH retention prunes (`articles` and
  `article_bodies`) via `NOT EXISTS (SELECT 1 FROM user_saves …)`, so
  a bookmark keeps its reader-view copy readable indefinitely. (The
  pre-existing maintenance comment anticipated exactly this.) Old
  saved articles don't pollute the feed — the feed query is windowed
  to `published_at >= now-7d`, so they only live on `/saved` + `/read`.
- **UI** — ☆/★ save button on every signed-in feed card, wired
  through the existing `cardSignals` Alpine component (new `saved`
  state + `toggleSave()`; `a.saved` batch-attached in `feed.py`
  exactly like `a.thumb`). New `/saved` page (scoped-style, Alpine
  per-row remove, "archived" vs "link only" badge keyed on
  `article_bodies.status`). "Saved" nav link in `base.html`.
  CSRF: ☆ uses `X-CSRF-Token` header (fetch); remove/mark-read same.
- **Tests** — `tests/test_saves.py` (11 cases: toggle/untoggle, auth
  401, folder passthrough/fallback, mark-read, anon redirect, list +
  empty state), same monkeypatch-DB pattern as `test_signals.py`.

### Server-side state touched

One DB migration (`user_saves`). **Load-bearing PRE-MERGE** (BUG-007
class): merged code reads `user_saves` on every signed-in feed load
and in `maintenance`. Logged in `manual-actions.md` → Open with full
inline SQL + pasted in chat; apply before merge, then Python App
restart. No new cron, env var, pip dep, or symlink.

### Verification

`py_compile` clean; all touched templates Jinja-parse. Flask
route/browser testing deferred to CI — sandbox has no Flask/pytest
(same documented limit as PRs #50/#56/#59). Logic reviewed.

### Parallel-session notes

Touches `feed.py`/`feed.html` (in-flight **PR #61** profiles),
`style.css` (PR #61 appends a different block), `base.html`,
`maintenance.py` (in-flight **PR #56** popularity/journalist —
different statements). All edits localized/append-style; rebased on
`origin/main` before opening the PR. Expect to rebase again behind
#61/#56 if they land first.

### PR

- Article save / bookmark (draft) — branch
  `claude/onboard-news-aggregator-Fx2d4`.

### Open items

- v2 (roadmap): folder management UI, "N unread in Read Later" home
  prompt, keyboard `s` to save, export OPML/Markdown, extended
  retention pairing with summaries/TTS.
- Signal Learning (Pri 8): saves live in `user_saves`, not
  `user_signals` — that session should read from `user_saves` (or add
  a `save` signal then) rather than double-implement.

---

## 2026-05-17 — Onboarding interview / cold-start (PR pending)

### Context

Roadmap Pri 7 / LOE 4, Theme A of the user-empowerment cluster. A basic
`/algo/onboarding` already existed (a 4-preset radio picker). Upgraded it
into a real cold-start interview so a new reader's first feed isn't the
generic `balanced` preset.

### What shipped

- **`app/onboarding.py`** (new, Flask-free — mirrors `algo_nl.py` /
  `language.py`). Pure helpers: `normalize_categories` (intersect with
  the `CATEGORIES` catalog, dedupe, catalog order), `lean_direction`
  (5-point balance key → signed `political_lean` direction; unknown →
  center), `build_onboarding_weights` (copy the `balanced` preset, layer
  on `category_filter` + `political_lean_direction`; never mutates
  `PRESETS`), `top_trusted_sources` (dedupe candidate source rows by
  name keeping the best reputation, sort, cap).
- **`app/routes/algo.py`** — only the `onboarding()` route changed
  (PR #59's editor surface left untouched). Now idempotent: if the user
  already has an algorithm it redirects to the editor instead of
  stacking a second active row. GET renders the interview (topics,
  political balance, top-reputation trusted sources). POST builds the
  tailored weights, inserts one `user_algorithms` row ("My starting
  feed"), and boosts each picked source via `user_source_prefs`
  (weight 1.5, reusing the PR #19 feed multiplier). Source ids are
  validated against the global active pool before any write.
- **`app/routes/auth_routes.py`** — signup now redirects to
  `algo.onboarding` (was `algo.index`), so the interview is the actual
  first-run screen.
- **`onboarding.html`** rewritten (3 sections, carries `csrf_field()`
  per the now-merged CSRF PR #58); single appended
  `.onboarding-interview` CSS block + a mobile rule.
- **`tests/test_onboarding.py`** (new) — 10 pure-helper cases (verified
  green via direct import; sandbox has no pytest/Flask, same documented
  limit as PR #50/#58) + 4 route cases (create_app + stubbed
  query/execute, mirrors `test_signals.py`) for the maintainer's full
  Flask run.

### Server-side state touched

None. No DB migration (`user_algorithms` / `user_source_prefs` already
on prod; `category_filter` lives inside `weights_json`), no new cron, no
new dependency, no env var. Standard Python App restart on deploy so the
new route/template load — not a tracked manual action.

### PR

- Draft PR pending on `claude/onboard-news-aggregator-pTXRY`.

---

## 2026-05-17 — Classifier/feature review: fixed BUG-016..019

### Context

User asked for a review of the classifiers and features for bugs and
poor performance. Read the full classifier/feature/ranking surface
end-to-end. 11 findings (4 high, 4 medium, 3 low); user chose to fix
the four high-severity ones. M/L items deferred (listed under Open).

### What shipped (PR #56, draft)

- **BUG-016 — popularity chronically under-counted.** First feature
  INSERT hard-wrote `popularity=0.0`; `popularity_poll` only UPDATEs
  existing rows, so anything trending while still `pending` lost its
  signal and nothing reconciled from `popularity_signals`. New shared
  `app.classifier.popularity_score()` (popularity_poll delegates to
  it); `classify_pending` seeds popularity from prior signals;
  `maintenance.py` nightly authoritative SQL reconciliation
  (`LN(1+score+2*comments)/LN(1+cap)`, 7-day window, idempotent) via
  shared `_POPULARITY_LN_DENOM` so Python & SQL agree.
- **BUG-017 — journalist_reputation penalized bylined articles.**
  `first_seen_at` defaulted to row-insert time → tenure≈0 → rep≈0.3,
  below the ~0.6 no-byline fallback. `_ensure_journalist()` seeds
  `first_seen_at` from `published_at`; `maintenance.py` floors rep at
  `GREATEST(avg_rep, 0.5*avg_rep+0.5*tenure)` (tenure clamped ≥0) so
  it's upside-only.
- **BUG-018 — `simhash==0` megacluster.** Empty/all-stopword articles
  got simhash 0 and clustered at Hamming-0 with every other zero,
  vanishing from the deduped feed behind a bogus canonical.
  `_assign_story_id` skips the simhash branch when `my_sim` falsy and
  excludes `a2.simhash=0`; `fetch_feeds` stores `NULL` for 0.
- **BUG-019 — LLM-fallback contamination permanent + unmarked.**
  `_classifier_version()` tags fallback rows `<ver>-nollm`; bounded
  `_reclassify_nollm()` re-runs the LLM over oldest tagged rows (one
  `LLM_BATCH_SIZE`/tick) when the pending queue is drained and budget
  remains, restoring the clean version. Persistent outage just leaves
  rows tagged. Per-tick log line gains `reclassified=N`.

### Code touched

- `app/classifier/rules.py` (popularity_score + `_POPULARITY_*`),
  `app/classifier/__init__.py` (export), `jobs/popularity_poll.py`
  (delegate; drop unused `import math`), `jobs/classify_pending.py`
  (popularity seed, `_classifier_version`, `_ensure_journalist`
  first_seen, simhash-0 guard, `_reclassify_nollm`),
  `jobs/fetch_feeds.py` (NULL for 0 simhash), `jobs/maintenance.py`
  (popularity reconcile + journalist rep floor).
- Tests: `test_rules.py` (+popularity_score & cron parity),
  `test_assign_story_id.py` (+simhash-0; `FakeCursor` gained a
  parallel `sql_log`, 2-tuple `calls` contract unchanged),
  `test_classify_pending.py` (new, +18 cases). Full suite **245
  passing** after rebase onto `origin/main` (PR #50/52/53/54/55).

### Server-side state touched

**None.** No DB migration / schema / cron / env / pip / symlink
change — code-only in cron scripts + a pure helper. Cron picks up new
code on the next tick; no web route changed (no Python App restart
strictly required). **No `manual-actions.md` entry.** Next-session
notes: rows written `classifier_version='v1'` during a *past* LLM
outage are not retroactively detectable (only rows tagged going
forward self-heal); existing `popularity=0.0` rows self-heal on the
next nightly `maintenance`; pre-existing `simhash=0` rows are now
ignored by clustering and age out.

### PRs

- **PR #56** — Classifier/feature review fixes (BUG-016..019). Draft.

### Open items (remaining review findings, not yet actioned)

- M5: `story_obscurity` counts only exact `title_hash` dupes, not the
  simhash cluster (wrong for re-headlined syndication; weight 0 latent).
- M6: no general rescore path beyond the `-nollm` heal.
- M7: `_assign_story_id` window keyed to NOW → dedup degrades during/
  after a classify backlog.
- M8: LLM partial responses fail silent; `max_tokens=2048` is an
  unguarded cliff if `LLM_BATCH_SIZE` is raised.
- L9: `info_density`/`reading_level` use the RSS blurb, not the
  extracted body; `_CAP_TOKEN` over-counts Title-Case headlines.
- L10: `popularity_poll._normalize_url` `lstrip("www.")` strips a char
  set, not the prefix — latent, harmless only because symmetric.
- L11: `country`/`region` written but unused in ranking/filters
  (spec feature #9 "geography" effectively unimplemented).
- Perf: simhash candidate query is an unindexable `BIT_COUNT` scan
  over 48h/pending row — fine now, watch as the catalog grows.

---

## Condensed history

Older entries, summarized. **Full verbatim text is in
`engineering-history-archive.md`** — grep it by PR# / BUG-ID / date for
the deep context (root causes, calibration notes, file lists). Every
server-side migration referenced below was applied on prod and is in
`manual-actions.md` → Completed; bug root causes are in `bugs.md`.

### 2026-05-17

- **CSRF protection + auth rate limiting (PR #58).** Hand-rolled
  signed double-submit-cookie CSRF (stdlib `hmac`/`secrets`, zero new
  dependency) enforced app-wide on every unsafe-method route via
  `before_request`; token delivered to forms via `csrf_field()`, to
  HTMX via an `htmx:configRequest` header hook, to plain `fetch()`
  POSTs via a `<meta>` tag + `window.csrfToken`. `account.unsubscribe`
  exempt (RFC 8058 URL-token auth). `CSRF_ENABLED` config (conftest
  disables suite-wide; `test_csrf.py` re-enables). Sliding-window
  in-process rate limit on `/auth/login`+`/auth/signup` (10 POSTs/
  5 min/IP, env-tunable; per-worker caveat). *Server:* none — new env
  vars have working defaults; restart on deploy. Full detail:
  `engineering-history-archive.md`.
- **Natural-language algorithm builder + user-empowerment cluster (PR #59).**
  Plain-English feed description → one Claude Haiku call → the existing
  3-axis `FEATURES` weight vector, pre-filling the `/algo` editor for
  review (never applied silently; reuses `/save`, **no DB migration**).
  New Flask-free `app/algo_nl.py` (lazy `anthropic`, `LLMUnavailable`
  fail-soft, every value clamped, unknown keys dropped); `POST
  /algo/describe` re-renders the editor. Shipped with a 10-item
  user-empowerment roadmap cluster (themes A/B/C). No cron/env/dep/
  symlink change. Full detail: `engineering-history-archive.md`.
- **BUG-015 — external trending sort: Google Trends/News (PR #53).**
  Popularity sort was HN-only; added pure `app/trending.py` +
  `jobs/trending_poll.py` cron filling `article_features.trending`
  from Google Trends + Google News RSS. Renamed the `popularity`
  sort to **Trending** (`ORDER BY f.trending DESC, score DESC`;
  legacy `?sort=popularity` aliased). Opt-in `trending` FEATURES
  entry (default weight 0). *Server (applied 2026-05-17, `manual-actions.md` → Completed):* `2026-05-17-trending.sql` ALTER +
  a new every-30-min `trending_poll` cron; restart. Full detail:
  `engineering-history-archive.md` / `bugs.md` BUG-015.
- **Techmeme-style discussion links — Reddit/HN (PR #52).**
  `popularity_poll` already matched Reddit/HN threads but discarded
  the permalink; now persists `permalink`+`subreddit` on
  `popularity_signals` and renders a `Discussion: Hacker News (142)
  · r/tech (89)` line on feed cards + a story-dossier panel (pure
  `app/discussion.py`). No new dep/API cost. *Server (applied
  2026-05-17, `manual-actions.md` → Completed):* one nullable-column
  migration (`2026-05-17-discussion-links.sql`); restart.
- **Engineering-history archive process (PR #51).** Introduced the
  ~14K-token / ~34 KB budget for this file plus
  `engineering-history-archive.md` (verbatim, on-demand) and the
  durable "Load-bearing production state" section that never ages
  out. Procedure lives in `engineering-session-wrapup.md` Step 1b.
  Docs-only; no server-side change.
- **BUG-013 + BUG-014 — Latin-script filter via py3langid (PR #50).**
  Added stage 3 to `app/language.py is_english`: when text clears
  stages 1+2 and has ≥24 Latin letters, run a cached `py3langid`
  detector and reject only on a confident non-English call
  (`top_prob ≥ 0.85` AND `english_prob < 0.10`) — deliberately biased
  to keep English. Replaced the briefly-shipped `langdetect==1.0.9`
  (BUG-014: sdist-only, won't build on the cPanel venv) with
  wheel-distributed `py3langid==0.3.0` (+`numpy`); import fails soft
  so it's not a site-down risk. *Server:* `pip install -r
  requirements.txt` run on prod 2026-05-17 (no wheel build —
  `manual-actions.md` → Completed); no DB/cron/env-var change. Full
  detail: `bugs.md` BUG-013/014.

### 2026-05-14

- **Feed sort selector — Relevance / Newest / Popularity (PR #48).**
  `/?sort=` query param; `_normalize_sort` + `_order_by_for_sort`
  pure helpers in `feed.py` swap the ORDER BY (newest →
  `published_at`, popularity → `f.popularity`); threshold / source-
  pref / visibility filters unchanged; category tabs + Load-more
  preserve `sort=`. *Server:* none (restart on deploy).

### 2026-05-13

- **BUG-012 — refresh-shuffle via score jitter (PR #46).** Feed was
  deterministic so reloads showed the same top-30; added an opt-in
  `jitter` kwarg to `build_score_sql` wrapping the score in
  `* (1 + RAND()*jitter)`, live feed passes `FEED_JITTER` (default
  0.10); digest / firehose / algo-preview stay deterministic.
  *Server:* none; `FEED_JITTER` env-var has a working default. Full
  detail: `bugs.md` BUG-012.
- **English-only article filter at fetch time (PR #42).** Pure
  `app/language.py is_english(title,summary,feed_language)` — stage 1
  trusts a non-English feed `<language>` tag, stage 2 rejects when
  >25% of letters fall outside Latin script ranges; wired into
  `fetch_feeds` before insert with a `skipped_lang` counter. Existing
  non-English rows left to age out (no backfill purge). Known gap:
  Latin-script European content leaked through — later closed by
  BUG-013/014 (py3langid stage 3, PR #50). *Server:* none (cron
  picks up the new module on its next tick).
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
