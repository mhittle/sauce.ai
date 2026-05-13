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

### 2026-05-13 — Cron entry: daily email digest
**Status:** open · **PR:** #23 · **Opened:** 2026-05-13

Adds the noon-UTC cron line that runs `jobs/send_digest.py` once a day.
Safe to add before any users opt in — the job exits as a no-op when no
candidates match. Skipping this means the digest feature ships but
never fires until the cron is in place.

**Where to add:** cPanel → "Cron Jobs" → "Add New Cron Job".

**Command** (replace `YOURACCOUNT`):

```
0 12 * * *  source /home/YOURACCOUNT/virtualenv/public_html/sauce.ai/news/3.11/bin/activate && cd /home/YOURACCOUNT/public_html/sauce.ai/news/jobs && python send_digest.py >> /home/YOURACCOUNT/public_html/sauce.ai/news/logs/cron.log 2>&1
```

**Verify:** After noon UTC the next day, tail `~/public_html/sauce.ai/news/logs/cron.log`
and look for `digest candidates: N` and `sent=… skipped_empty=… failed=… candidates=…`
lines.

---

### 2026-05-13 — Migration: users digest columns
**Status:** open · **PR:** #23 · **Opened:** 2026-05-13 ·
**File reference:** `news/seed/migrations/2026-05-13-digest.sql`

Adds the three opt-in/tracking columns to `users` that the daily email
digest needs: `digest_enabled` (0/1 toggle), `digest_unsub_token`
(40-hex; minted on first opt-in, rotated on unsubscribe),
`digest_last_sent_at` (resend guard). Until this runs on prod, the
`POST /account/settings` route will error when a user toggles the
digest on.

**Where to run:** phpMyAdmin → SQL tab → database `lt1ih6uyy2z6_news`.

**SQL:**

```sql
ALTER TABLE users
  ADD COLUMN digest_enabled      TINYINT(1) NOT NULL DEFAULT 0 AFTER created_at,
  ADD COLUMN digest_unsub_token  CHAR(40) NOT NULL DEFAULT '' AFTER digest_enabled,
  ADD COLUMN digest_last_sent_at DATETIME DEFAULT NULL AFTER digest_unsub_token,
  ADD KEY idx_users_digest (digest_enabled, digest_last_sent_at);
```

**Verify:**

```sql
SHOW COLUMNS FROM users LIKE 'digest_%';
```

Should return three rows.

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

(none yet)
