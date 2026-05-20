# sauce.ai/news — Manual prod actions tracker

Outstanding server-side actions that must be performed manually on prod
(usually via phpMyAdmin or cPanel) before a feature works end-to-end.
**Reviewed at the start of every engineering session** per
`new-engineering-session-instructions.md` — the agent asks the user
whether each open item has been completed.

When a new manual action is required (e.g. DB migration, cron entry,
symlink, env-var change), the session that ships the feature must:

1. Append a new entry to the **Open** section below, with the **full
   command/SQL inline** (not just a path to a file), so it's
   copy-paste-ready straight from this doc. **Substitute the real prod
   account `lt1ih6uyy2z6` into every path** — do NOT leave `YOURACCOUNT`
   placeholders in this doc or in the chat paste. (`INSTALL.txt` keeps
   `YOURACCOUNT` because it's a generic fresh-install template; this
   tracker and the chat paste are operational and must be runnable
   verbatim.)
2. Also paste the same command/SQL into chat so the user can act on it
   immediately without opening any files.
3. After the user confirms completion, move the entry to **Completed**
   with the completion date.

If the migration also lives as a `news/seed/migrations/*.sql` file,
reference the filename in the entry — but the entry must still carry the
full SQL inline. The file is for fresh installs / replay; this doc is
for the live prod database.

## Conventions

Each entry: title, status, opened date, related PR, exact command,
where to run it, verification step, and (when done) completion date.

Status values: `open` (action required) · `completed` (verified done).

Sort **Open** newest-first. **Completed** newest-first.

---

## Open

### 2026-05-20 — Source catalog import (+1151 new sources)
**Status:** open · **PR:** #91 (merged 2026-05-20) · **Opened:** 2026-05-20

`seed/source_lean.csv` grew 768 → 1919 sources (added 1151 hand-curated
outlets + Substacks + Medium pubs + engineering blogs). To load them on
prod, sign in as admin and POST `/admin/feeds/import` (the "Re-import
seed CSV" button on `/admin/feeds`). The import is **idempotent** —
existing rows are updated, new rows inserted, keyed on `feed_url`. Dead
feeds self-deactivate at `error_count=10` per the existing cron worker,
so there's no need to vet 1100+ URLs by hand before importing.

**Action (one of):**

1. **Browser:** Sign in as admin → visit `https://sauce.ai/news/admin/feeds`
   → click **Re-import seed CSV** (the form POSTs to
   `/admin/feeds/import`). Wait ~30 s for the upsert loop to finish; you
   get a redirect with `?added=N&updated=M` in the URL.
2. **curl (with admin session cookie):**

   ```bash
   curl -X POST -b "session=<your-admin-session-cookie>" \
     -H "X-CSRF-Token: <token-from-meta-tag>" \
     https://sauce.ai/news/admin/feeds/import
   ```

No DB migration, no cron change, no env var, no pip install, no symlink.
Python App restart not required (the import code rereads the CSV from
disk every time the button is clicked, and `fetch_feeds` picks up new
`sources` rows on its next 15-min tick).

**Verify:** `https://sauce.ai/news/admin/feeds` row count jumps to
~1919. Within an hour or two, `logs/cron.log` shows `fetch_feeds` hitting
the new feed URLs; some will error and `error_count` will climb on
dead/wrong ones (expected — they auto-deactivate at 10). Spot-check a
few new sources for fresh articles on `/firehose`.

---



---

## Completed

### 2026-05-20 — Migration: 12 perceptual feature columns + catalog rows
**Status:** completed · **PR:** #84 (merged 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-20 ·
**File reference:** `news/seed/migrations/2026-05-20-perception-features.sql`

Added 6 LLM-judged perceptual columns (`tone_calmness`,
`sensationalism`, `analysis_depth`, `emotional_charge`, `hedging`,
`solution_orientation`, all DEFAULT 0.5) and 6 rule-based structural
columns (`headline_length`, `caps_ratio`, `punctuation_intensity`,
`numeric_density`, `question_headline`, `quote_present`, all DEFAULT
0) to `article_features`, plus the matching 12 `feature_catalog`
rows. Load-bearing (BUG-007 class): `jobs/classify_pending.py` INSERTs
into all 12 new columns on every tick after the deploy and would have
errored hard on the missing columns. User confirmed the ALTER + INSERT
were run via phpMyAdmin against `lt1ih6uyy2z6_news` and the Python App
restarted (2026-05-20), so `classify_pending` is now writing the new
columns and `/algo` exposes the 12 new sliders. In the repo via
`schema.sql` + `feature_catalog.sql` + the migration file so fresh
installs replay it. Folded into the load-bearing "Applied prod schema
migrations" line in `engineering-history.md`.

**SQL applied:**

```sql
ALTER TABLE article_features
  ADD COLUMN tone_calmness         FLOAT NOT NULL DEFAULT 0.5 AFTER trending,
  ADD COLUMN sensationalism        FLOAT NOT NULL DEFAULT 0.5 AFTER tone_calmness,
  ADD COLUMN analysis_depth        FLOAT NOT NULL DEFAULT 0.5 AFTER sensationalism,
  ADD COLUMN emotional_charge      FLOAT NOT NULL DEFAULT 0.5 AFTER analysis_depth,
  ADD COLUMN hedging               FLOAT NOT NULL DEFAULT 0.5 AFTER emotional_charge,
  ADD COLUMN solution_orientation  FLOAT NOT NULL DEFAULT 0.5 AFTER hedging,
  ADD COLUMN headline_length       FLOAT NOT NULL DEFAULT 0   AFTER solution_orientation,
  ADD COLUMN caps_ratio            FLOAT NOT NULL DEFAULT 0   AFTER headline_length,
  ADD COLUMN punctuation_intensity FLOAT NOT NULL DEFAULT 0   AFTER caps_ratio,
  ADD COLUMN numeric_density       FLOAT NOT NULL DEFAULT 0   AFTER punctuation_intensity,
  ADD COLUMN question_headline     FLOAT NOT NULL DEFAULT 0   AFTER numeric_density,
  ADD COLUMN quote_present         FLOAT NOT NULL DEFAULT 0   AFTER question_headline;

INSERT INTO feature_catalog (feature_key, label, type, range_min, range_max, description, is_active, sort_order) VALUES
  ('tone_calmness',        'Tone (calm)',           'scale', 0, 1, 'LLM judgment: 1 = calm, measured; 0 = alarmist, urgent.',          1, 120),
  ('sensationalism',       'Sensationalism',        'scale', 0, 1, 'LLM judgment: 1 = sensational/clickbait phrasing; 0 = plain.',     1, 125),
  ('analysis_depth',       'Analysis depth',        'scale', 0, 1, 'LLM judgment: 1 = analytical/explainer; 0 = breaking-news brief.', 1, 130),
  ('emotional_charge',     'Emotional charge',      'scale', 0, 1, 'LLM judgment: 1 = emotionally loaded language; 0 = neutral.',      1, 135),
  ('hedging',              'Hedging',               'scale', 0, 1, 'LLM judgment: 1 = heavy hedging ("may", "could"); 0 = confident assertion.', 1, 140),
  ('solution_orientation', 'Solution orientation',  'scale', 0, 1, 'LLM judgment: 1 = solution-focused; 0 = problem-focused.',         1, 145),
  ('headline_length',      'Headline length',       'scale', 0, 1, 'Rule-based: normalized title word count, capped at 24.',           1, 150),
  ('caps_ratio',           'ALL-CAPS shouting',     'scale', 0, 1, 'Rule-based: uppercase letter ratio in title (shoutiness proxy).',  1, 155),
  ('punctuation_intensity','Punctuation intensity', 'scale', 0, 1, 'Rule-based: !? density per word in title+summary.',                1, 160),
  ('numeric_density',      'Data density',          'scale', 0, 1, 'Rule-based: digit-run density per word.',                          1, 165),
  ('question_headline',    'Question headline',     'scale', 0, 1, 'Rule-based: 1 if title ends with `?`, else 0.',                    1, 170),
  ('quote_present',        'Direct quote',          'scale', 0, 1, 'Rule-based: 1 if a direct quoted span appears in title or summary.', 1, 175);
```

### 2026-05-20 — Migration: algorithm_term_prefs (per-algorithm keyword mute & boost)
**Status:** completed · **PR:** #82 (merged 2026-05-20) ·
**Opened:** 2026-05-20 · **Completed:** 2026-05-20 ·
**File reference:** `news/seed/migrations/2026-05-20-algorithm-term-prefs.sql`

Created `algorithm_term_prefs`, backing the new "Keywords" tab on
`/algo`. `routes/feed.py` reads it for the signed-in user's active
algorithm on every feed load and unions the rows with `user_term_prefs`
before scoring. **BUG-007 class** — the merged code 500'd the signed-in
feed on a missing table (anon / `/firehose` / digest unaffected) for
the gap between deploy and migration. User confirmed the `CREATE TABLE`
was run via phpMyAdmin against `lt1ih6uyy2z6_news` and the Python App
restarted (2026-05-20), so the signed-in feed + new Keywords tab are
safe. In the repo via `schema.sql` + the migration file so fresh
installs replay it. Folded into the load-bearing "Applied prod schema
migrations" line in `engineering-history.md`.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS algorithm_term_prefs (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  algorithm_id INT UNSIGNED NOT NULL,
  term         VARCHAR(128) NOT NULL,
  mode         ENUM('mute','boost') NOT NULL,
  weight       FLOAT NOT NULL DEFAULT 1.5,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_algo_term (algorithm_id, term),
  KEY idx_algo_term_algo (algorithm_id),
  CONSTRAINT fk_algo_term_algo FOREIGN KEY (algorithm_id)
    REFERENCES user_algorithms (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:** `/algo` Keywords tab renders for a signed-in user; adding a
mute term hides matching articles on `/`; adding a boost term raises
them. `SHOW CREATE TABLE algorithm_term_prefs\G` lists the FK to
`user_algorithms`.

### 2026-05-17 — Migration: user_term_prefs (keyword mute & boost)
**Status:** completed · **PR:** #77 (merged 2026-05-17) ·
**Opened:** 2026-05-17 · **Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-term-prefs.sql`

Created `user_term_prefs`, backing per-user keyword **mute**
(hard-filter) and **boost** (score multiplier) at `/terms`.
`routes/feed.py` reads it on every signed-in feed load (BUG-007 class
if absent). User confirmed the `CREATE TABLE` was run via phpMyAdmin
against `lt1ih6uyy2z6_news` and the Python App restarted (2026-05-17),
so the signed-in feed is safe. Anonymous feed / `/firehose` / digest
were unaffected throughout. In the repo via `schema.sql` + the
migration file so fresh installs replay it.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS user_term_prefs (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED NOT NULL,
  term       VARCHAR(128) NOT NULL,
  mode       ENUM('mute','boost') NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.5,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_term_pref (user_id, term),
  KEY idx_term_pref_user (user_id),
  CONSTRAINT fk_term_pref_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Verify:** `/terms` returns 200 for a signed-in user; a muted term
drops matching articles from `/`; a boosted term raises them.

### 2026-05-17 — Migration: articles FULLTEXT index (article search)
**Status:** completed · **PR:** #70 · **Opened:** 2026-05-17 ·
**Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-search-fulltext.sql`

Added an InnoDB FULLTEXT index over `articles(title, summary)` backing
the new `/search` route + nav search box. User confirmed the ALTER was
run via phpMyAdmin against `lt1ih6uyy2z6_news` and the Python App
restarted (2026-05-17). `/search` is now safe to merge (the BUG-007-class
missing-index 500 is cleared). In the repo via `schema.sql` + the
migration file so fresh installs replay it.

**SQL applied:**

```sql
ALTER TABLE articles
  ADD FULLTEXT INDEX ft_articles_search (title, summary);
```

**Verify:** `https://sauce.ai/news/search?q=election` returns 200 with
ranked results (not a 500). `SHOW INDEX FROM articles WHERE Key_name =
'ft_articles_search';` lists the FULLTEXT index.

### 2026-05-17 — Migration: trending-topics snapshot tables (/trending page)
**Status:** completed · **PR:** #71 (Trending topics view, roadmap Pri 7) ·
**Opened:** 2026-05-17 · **Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-trending-topics.sql`

Added `trending_topics` + `trending_topic_articles`, the snapshot the
`/trending` page reads. The existing every-30-min `trending_poll` cron
fills both tables on its next tick — no new cron, no backfill. User
confirmed the SQL was run via phpMyAdmin against `lt1ih6uyy2z6_news`
and the Python App restarted (2026-05-17). The feed's Trending *sort*
(`article_features.trending`, a different column) was unaffected
throughout.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS trending_topics (
  topic_key   CHAR(40) NOT NULL,
  label       VARCHAR(255) NOT NULL,
  origin      VARCHAR(16) NOT NULL DEFAULT '',
  heat        FLOAT NOT NULL DEFAULT 0,
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (topic_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS trending_topic_articles (
  topic_key   CHAR(40) NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  match_score FLOAT NOT NULL DEFAULT 0,
  PRIMARY KEY (topic_key, article_id),
  KEY idx_tta_article (article_id),
  CONSTRAINT fk_tta_article FOREIGN KEY (article_id)
    REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-17 — Migration: user_saves (article save / bookmark)
**Status:** completed · **PR:** #64 (merged 2026-05-17) ·
**Opened:** 2026-05-17 · **Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-user-saves.sql`

Created `user_saves`, backing the star/bookmark button on feed cards
and the `/saved` page. Load-bearing (BUG-007 class): the table was NOT
confirmed applied before PR #64 merged, so signed-in `/` 500'd and the
nightly `maintenance` job would have errored in the interval between
deploy and migration. User ran the `CREATE TABLE user_saves` SQL via
phpMyAdmin against `lt1ih6uyy2z6_news` and restarted the Python App
(2026-05-17) — signed-in feed recovered. **Process note:** recurrence
of the BUG-007 pattern (load-bearing migration not applied pre-merge);
the migration should have gated the PR merge, not trailed it.

### 2026-05-17 — Migration: popularity_signals discussion columns
**Status:** completed · **PR:** #52 · **Opened:** 2026-05-17 ·
**Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-discussion-links.sql`

Added nullable `permalink` + `subreddit` to `popularity_signals` so the
feed card and story dossier can render a Techmeme-style "Discussion:"
line linking to the Reddit/HN thread (`popularity_poll` already matched
those threads for the popularity score; it now also writes the
permalink). User confirmed the ALTER was run via phpMyAdmin against
`lt1ih6uyy2z6_news` and the Python App restarted (2026-05-17).

**SQL applied:**

```sql
ALTER TABLE popularity_signals
  ADD COLUMN permalink VARCHAR(1024) DEFAULT NULL AFTER comments,
  ADD COLUMN subreddit  VARCHAR(64) DEFAULT NULL AFTER permalink;
```

---

### 2026-05-17 — Migration + cron: external trending sort (BUG-015)
**Status:** completed · **PR:** #53 · **Opened:** 2026-05-17 ·
**Completed:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-trending.sql`

Added `article_features.trending` (0..1, external trending-topic match)
and the new `trending_poll` cron that fills it from Google Trends +
Google News RSS. The renamed **Trending** feed sort orders by this
column. User confirmed the migration was applied, the every-30-min
cron added, and the Python App restarted.

**SQL applied (phpMyAdmin against `lt1ih6uyy2z6_news`):**

```sql
ALTER TABLE article_features
  ADD COLUMN trending FLOAT NOT NULL DEFAULT 0 AFTER paywall;
```

**Cron added (cPanel → "Cron Jobs"):**

```cron
# every 30 min: external trending poll (Google Trends + Google News RSS)
*/30 * * * *  source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python trending_poll.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1
```

Python App restarted so the renamed sort + new column load. Verify on
prod: `/?sort=trending` returns 200 and is no longer HN-only;
`logs/cron.log` shows a `trending_poll` line like
`topics=T gnews=G articles=N matched=M` within ~30 min.

---

### 2026-05-17 — pip install -r requirements.txt (py3langid for BUG-013/BUG-014)
**Status:** completed · **PR:** #50 (BUG-013, BUG-014) · **Opened:** 2026-05-17 · **Completed:** 2026-05-17

User confirmed `pip install -r requirements.txt` was run on prod
(2026-05-17), installing `py3langid==0.3.0` (+ wheel-distributed
`numpy`). The European-language filter (stage 3 of `is_english`) is
now live: `jobs/fetch_feeds.py` is a fresh per-tick cron process so it
picks up py3langid on its next tick regardless of a Passenger restart
(web routes don't use the detector, so no site-facing restart was
strictly required). BUG-013/BUG-014 are now effective in production.

Expect `skipped_lang=N` to rise in `logs/cron.log` over the next few
`fetch_feeds` ticks, and German/Spanish/Finnish content to clear out
of the feed over ~7 days as pre-existing rows age out (the filter is
fetch-time only; it does not purge rows already in `articles`).

**Commands run (account `lt1ih6uyy2z6`):**

```bash
# In cPanel Terminal, paste cPanel's "Enter to the virtual environment"
# command for the news app, then:
source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate \
  && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news
pip install -r requirements.txt
```

**Verify:**

```bash
/home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/python \
  -c "from py3langid.langid import LanguageIdentifier, MODEL_FILE; LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True); import numpy; print('py3langid ok, numpy', numpy.__version__)"
```

---

### 2026-05-13 — Migration: story_dossiers (framing-summary cache)
**Status:** completed · **PR:** #43 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-story-dossiers.sql`

Added the `story_dossiers` table that caches each story cluster's
LLM-generated framing summary keyed by canonical `articles.id` and
invalidated by `member_signature` (sha1 of sorted member ids). The
`/story/<id>` route writes to this table on the first uncached view per
signature. Ran via phpMyAdmin against `lt1ih6uyy2z6_news`; Python App
restarted post-migration so the new `story_bp` blueprint registers.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS story_dossiers (
  story_id         BIGINT UNSIGNED NOT NULL,
  member_signature CHAR(40) NOT NULL,
  summary_text     TEXT NOT NULL,
  article_count    INT UNSIGNED NOT NULL DEFAULT 0,
  lean_buckets     VARCHAR(16) NOT NULL DEFAULT '',
  model            VARCHAR(64) NOT NULL DEFAULT '',
  generated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (story_id),
  CONSTRAINT fk_dossier_story FOREIGN KEY (story_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-13 — Cron entries: three discover_* jobs
**Status:** completed · **PR:** #38 · **Opened:** 2026-05-13 · **Completed:** 2026-05-13

Three new cron lines added in cPanel after the candidate_sources
migration ran. All three jobs are wrapped in `job_lock` and no-op
safely on an empty queue.

**Cron lines applied (account substituted):**

```cron
# hourly (15 past): source discovery harvest (Reddit/HN domain mining)
15  * * * *   source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python discover_harvest.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1

# nightly 4:00am UTC: source discovery validation
0   4 * * *   source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python discover_promote.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1

# weekly Monday 5:00am UTC: LLM-suggested source discovery
0   5 * * 1   source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news/jobs && python discover_llm.py >> /home/lt1ih6uyy2z6/public_html/sauce.ai/news/logs/cron.log 2>&1
```

---

### 2026-05-13 — Migration: candidate_sources (automated source discovery)
**Status:** completed · **PR:** #38 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-discovery.sql`

Added the `candidate_sources` table that backs the new hourly Reddit/HN
harvest, weekly LLM-suggestion pass, and nightly RSS auto-discovery
jobs. Ran in phpMyAdmin against `lt1ih6uyy2z6_news`; Python App
restarted post-migration.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS candidate_sources (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  domain        VARCHAR(255) NOT NULL,
  feed_url      VARCHAR(1024) DEFAULT NULL,
  name          VARCHAR(255) DEFAULT NULL,
  homepage_url  VARCHAR(1024) DEFAULT NULL,
  category      VARCHAR(64) DEFAULT NULL,
  score         INT NOT NULL DEFAULT 0,
  first_seen_via VARCHAR(32) NOT NULL,
  last_seen_via  VARCHAR(32) NOT NULL,
  first_seen_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  state         ENUM('pending','validated','approved','rejected','blacklisted')
                NOT NULL DEFAULT 'pending',
  reject_reason VARCHAR(255) DEFAULT NULL,
  validation_attempted_at DATETIME DEFAULT NULL,
  validation_error VARCHAR(255) DEFAULT NULL,
  promoted_source_id INT UNSIGNED DEFAULT NULL,
  notes         TEXT,
  PRIMARY KEY (id),
  UNIQUE KEY uk_candidate_domain (domain),
  KEY idx_candidate_state_score (state, score),
  KEY idx_candidate_last_seen (last_seen_at),
  CONSTRAINT fk_candidate_source FOREIGN KEY (promoted_source_id)
    REFERENCES sources (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-13 — pip install -r requirements.txt (trafilatura for PR #21)
**Status:** completed · **PR:** #21 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13

PR #21 added `trafilatura==1.12.2` (+ `lxml`) to `requirements.txt` for
the in-app reader's body extractor. The cPanel "Run Pip Install" button
in Setup Python App was greyed out, so the install was run manually
from cPanel Terminal after activating the venv. `classify_pending` is
the only consumer (lazy import in `app/extractor.py`); web routes were
unaffected, so the site itself stayed up while this was pending.

**Commands run:**

```bash
# In cPanel Terminal, after pasting cPanel's "Enter to the virtual
# environment" command for the news app:
source /home/YOURACCOUNT/virtualenv/public_html/sauce.ai/news/3.11/bin/activate \
  && cd /home/YOURACCOUNT/public_html/sauce.ai/news
pip install -r requirements.txt
```

**Post:** Python App restarted via cPanel.

---

### 2026-05-13 — Migration: sources.owner_id (user-added feeds)
**Status:** completed · **PR:** #29 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-user-sources.sql`

Added the `owner_id` column to `sources` so user-added RSS feeds can be
scoped to the user that added them. NULL = global pool (all existing
rows); non-null = personal source visible only to that user. Site was
500'ing on every reader route until this ran because `feed.py:65` and
`firehose.py:49` reference `s.owner_id` in the visibility WHERE clause
on every page load. Ran via phpMyAdmin against `lt1ih6uyy2z6_news`,
Python App restarted, site recovered. Filed as BUG-007 during recovery.

**SQL applied:**

```sql
ALTER TABLE sources
  ADD COLUMN owner_id INT UNSIGNED DEFAULT NULL AFTER region,
  ADD KEY idx_sources_owner (owner_id),
  ADD CONSTRAINT fk_sources_owner FOREIGN KEY (owner_id)
    REFERENCES users (id) ON DELETE CASCADE;
```

---

### 2026-05-13 — Migration: user_signals + user_source_prefs
**Status:** completed · **PR:** #19 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-signals.sql`

Added the two tables that back thumbs up/down: `user_signals` (generic
per-user signal stream, sized for the full Signal Learning vocabulary)
and `user_source_prefs` (per-user-source weight, 0 = hidden, 0.5 =
downweighted, default 1.0). `feed.py` LEFT JOINs `user_source_prefs` for
signed-in users so this also contributed to the BUG-007 outage. Ran in
the same phpMyAdmin session as the owner_id ALTER.

**SQL applied:**

```sql
CREATE TABLE IF NOT EXISTS user_signals (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  signal_type VARCHAR(32) NOT NULL,
  value       FLOAT DEFAULT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_signal_binary (user_id, article_id, signal_type),
  KEY idx_signal_user_type_ts (user_id, signal_type, created_at),
  KEY idx_signal_article_type (article_id, signal_type),
  CONSTRAINT fk_signal_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_signal_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_source_prefs (
  user_id    INT UNSIGNED NOT NULL,
  source_id  INT UNSIGNED NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, source_id),
  CONSTRAINT fk_usp_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_usp_source FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 2026-05-13 — Migration: article dedup (story_id + simhash)
**Status:** completed · **PR:** #24 · **Opened:** 2026-05-13 ·
**Completed:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-dedup.sql`

Added `articles.simhash`, `articles.story_id`, and the
`(story_id, published_at)` index; backfilled `story_id = id` for legacy
rows. User ran the SQL via phpMyAdmin; Python App restart still required
once the PR merges so the new code path picks up the columns.

**SQL applied:**

```sql
ALTER TABLE articles
  ADD COLUMN simhash  BIGINT UNSIGNED DEFAULT NULL AFTER title_hash,
  ADD COLUMN story_id BIGINT UNSIGNED DEFAULT NULL AFTER simhash,
  ADD KEY idx_articles_story (story_id, published_at);

UPDATE articles SET story_id = id WHERE story_id IS NULL;
```

---

### 2026-05-13 — Cron entry: daily email digest
**Status:** completed · **PR:** #23 · **Opened:** 2026-05-13 · **Completed:** 2026-05-13

Noon-UTC cron line for `jobs/send_digest.py` added in cPanel. Will fire
its first real run at the next noon UTC; until users opt in it exits as
a no-op.

---

### 2026-05-13 — Migration: users digest columns
**Status:** completed · **PR:** #23 · **Opened:** 2026-05-13 · **Completed:** 2026-05-13

`users.digest_enabled`, `digest_unsub_token`, `digest_last_sent_at` plus
`idx_users_digest` index added on prod (`lt1ih6uyy2z6_news`). Python App
restarted. `/account/settings` toggle is now safe to use.
