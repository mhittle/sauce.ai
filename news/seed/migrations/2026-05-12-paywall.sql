-- Migration: add paywall feature column.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
-- Idempotent in spirit: re-running will error on the ADD COLUMN (ignore).
--
-- Fresh installs get the column from schema.sql.

ALTER TABLE article_features
  ADD COLUMN paywall FLOAT NOT NULL DEFAULT 0 AFTER source_obscurity;

-- Existing classified rows stay at 0 (no paywall). The next classify_pending
-- cycle does not re-score historical articles; if you want to backfill,
-- re-run classify_pending against the older rows after setting them to
-- status='pending' (acceptable for v1 since paywall is opt-in).
