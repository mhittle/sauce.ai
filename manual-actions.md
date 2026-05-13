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

### 2026-05-13 — Migration: sources.owner_id (user-added feeds)
**Status:** open · **PR:** #TBD (this session) · **Opened:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-user-sources.sql`

Adds the `owner_id` column to `sources` so user-added RSS feeds can be
scoped to the user that added them. NULL = global pool (all existing
rows); non-null = personal source visible only to that user's `/`,
`/firehose`, and `/sources`. Until this runs on prod, `POST /sources/`
INSERTs error and `/sources` page query for personal sources errors.
The visibility filters in `feed.py` and `firehose.py` reference
`s.owner_id` so the reader-side pages will also 500 until the column
exists.

**Where to run:** phpMyAdmin → SQL tab → database `lt1ih6uyy2z6_news`.

**SQL:**

```sql
ALTER TABLE sources
  ADD COLUMN owner_id INT UNSIGNED DEFAULT NULL AFTER region,
  ADD KEY idx_sources_owner (owner_id),
  ADD CONSTRAINT fk_sources_owner FOREIGN KEY (owner_id)
    REFERENCES users (id) ON DELETE CASCADE;
```

**Verify:**

```sql
SHOW COLUMNS FROM sources LIKE 'owner_id';
```

Should return one row with `Null=YES`, `Default=NULL`.

**Post:** Restart the Python App (cPanel → Setup Python App → Restart).

---

### 2026-05-13 — Migration: user_signals + user_source_prefs
**Status:** open · **PR:** #19 · **Opened:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-signals.sql`

Adds the two tables that back the thumbs up/down feature: `user_signals`
(generic per-user signal stream, sized for the full Signal Learning
vocabulary) and `user_source_prefs` (per-user-source weight, 0 = hidden,
0.5 = downweighted, default 1.0). Until this runs on prod, the
`POST /signal/<id>/<type>` and `POST /signal/source/<id>` route INSERTs
will error.

**Where to run:** phpMyAdmin → SQL tab → database `lt1ih6uyy2z6_news`.

**SQL:**

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

**Verify:**

```sql
SHOW TABLES LIKE 'user_signals';
SHOW TABLES LIKE 'user_source_prefs';
```

Both should return one row.

**Post:** Restart the Python App (cPanel → Setup Python App → Restart).

---

## Completed

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
