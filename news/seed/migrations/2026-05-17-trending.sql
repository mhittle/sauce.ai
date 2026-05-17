-- Migration: add the external-trending feature column (BUG-015).
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
-- Idempotent in spirit: re-running will error on the ADD COLUMN (ignore).
--
-- Fresh installs get the column from schema.sql.

ALTER TABLE article_features
  ADD COLUMN trending FLOAT NOT NULL DEFAULT 0 AFTER paywall;

-- Existing classified rows stay at 0 until the new `trending_poll` cron
-- job runs; it scores the whole rolling window (TRENDING_WINDOW_DAYS,
-- default 2) on every tick, so there is no separate backfill step.
