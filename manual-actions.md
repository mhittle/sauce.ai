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
   copy-paste-ready straight from this doc.
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

### 2026-05-17 — pip install -r requirements.txt (py3langid for BUG-013/BUG-014)
**Status:** open · **PR:** #50 (BUG-013, BUG-014) · **Opened:** 2026-05-17

BUG-013 fix adds a language-detector stage 3 to the English-only
filter (catches Latin-script European content — German/Spanish/
Finnish — that the non-Latin script heuristic can't). The dependency
is `py3langid==0.3.0` (pulls `numpy>=2.0.0`). It replaces the original
`langdetect==1.0.9`, which was BUG-014: langdetect is sdist-only and
its old setup.py fails to build under modern PEP 517/setuptools on the
cPanel venv. py3langid ships a prebuilt wheel and numpy ships
manylinux cp311 wheels, so `pip install` is a plain download — no
build step, so the BUG-014 failure class cannot recur.

The import is lazy and fails soft: **the site does NOT 500 without
this** and the fetch pipeline keeps running, but the new European-
language filtering is inert until py3langid is installed — non-English
Latin-script articles will keep leaking into the feed until then. Only
`jobs/fetch_feeds.py` (cron) consumes it; web routes are unaffected.

The cPanel "Run Pip Install" button in Setup Python App has been greyed
out historically — run from cPanel Terminal after activating the venv.

**Commands (account `lt1ih6uyy2z6`):**

```bash
# In cPanel Terminal, paste cPanel's "Enter to the virtual environment"
# command for the news app, then:
source /home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/activate \
  && cd /home/lt1ih6uyy2z6/public_html/sauce.ai/news
pip install -r requirements.txt
```

**Then:** restart the Python App via cPanel (Setup Python App ->
Restart) so any already-running workers pick up the new package.

**Verify:**

```bash
/home/lt1ih6uyy2z6/virtualenv/public_html/sauce.ai/news/3.11/bin/python \
  -c "from py3langid.langid import LanguageIdentifier, MODEL_FILE; LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True); import numpy; print('py3langid ok, numpy', numpy.__version__)"
```

Then watch the next few `fetch_feeds` ticks in `logs/cron.log`:
`skipped_lang=N` should rise once European feeds start getting
rejected. Spot-check the feed for German/Spanish/Finnish content
clearing out over the following ~7 days as pre-existing rows age out
of the window (the filter is fetch-time only; it does not purge rows
already in `articles`).

---

### 2026-05-17 — Migration: popularity_signals discussion columns
**Status:** open · **PR:** (Techmeme-style discussion links, draft) ·
**Opened:** 2026-05-17 ·
**File reference:** `news/seed/migrations/2026-05-17-discussion-links.sql`

Adds `permalink` + `subreddit` to `popularity_signals` so the feed card
and story dossier can show a Techmeme-style "Discussion:" line linking
to the Reddit/HN thread. `popularity_poll` already matched these
threads for the popularity score; it now also writes the permalink.

**Run before merging the PR** (and before the next `popularity_poll`
tick): the web feed/dossier `SELECT permalink, subreddit` and the
`popularity_poll` INSERT lists the new columns, so both error until the
ALTER runs. Run via phpMyAdmin against `lt1ih6uyy2z6_news`, then
restart the Python App from cPanel.

**SQL to apply:**

```sql
ALTER TABLE popularity_signals
  ADD COLUMN permalink VARCHAR(1024) DEFAULT NULL AFTER comments,
  ADD COLUMN subreddit  VARCHAR(64) DEFAULT NULL AFTER permalink;
```

**Verify:**

```sql
SHOW COLUMNS FROM popularity_signals LIKE 'permalink';
SHOW COLUMNS FROM popularity_signals LIKE 'subreddit';
```

Then after one `popularity_poll` tick (~30 min):

```sql
SELECT COUNT(*) FROM popularity_signals WHERE permalink IS NOT NULL;
```

should be non-zero.

---

## Completed

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
