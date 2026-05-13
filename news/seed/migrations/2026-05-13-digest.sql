-- Migration: add daily email digest opt-in fields to users.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
-- Re-running will error on the ADD COLUMNs (ignore).
--
-- Fresh installs get these columns from schema.sql.

ALTER TABLE users
  ADD COLUMN digest_enabled      TINYINT(1) NOT NULL DEFAULT 0 AFTER created_at,
  ADD COLUMN digest_unsub_token  CHAR(40) NOT NULL DEFAULT '' AFTER digest_enabled,
  ADD COLUMN digest_last_sent_at DATETIME DEFAULT NULL AFTER digest_unsub_token,
  ADD KEY idx_users_digest (digest_enabled, digest_last_sent_at);
