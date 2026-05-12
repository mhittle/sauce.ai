-- Migration: add obscurity features (story + source) and supporting columns.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
-- Idempotent: safe to re-run; will error if columns already exist (ignore those errors).
--
-- This is for upgrades only. Fresh installs get these columns from schema.sql.

ALTER TABLE articles
  ADD COLUMN title_hash CHAR(40) DEFAULT NULL AFTER title,
  ADD KEY idx_articles_title_hash (title_hash, fetched_at);

ALTER TABLE sources
  ADD COLUMN article_count_30d INT UNSIGNED NOT NULL DEFAULT 0 AFTER region;

ALTER TABLE article_features
  ADD COLUMN story_obscurity  FLOAT NOT NULL DEFAULT 0.5 AFTER popularity,
  ADD COLUMN source_obscurity FLOAT NOT NULL DEFAULT 0.5 AFTER story_obscurity;

-- Backfill title_hash for existing articles. fetch_feeds.py will populate
-- the column going forward; this hashes whatever's in the legacy rows.
-- Hash matches the normalize_title() result in app/classifier/rules.py:
--   lowercase, strip punctuation, collapse whitespace.
UPDATE articles
SET title_hash = SHA1(
  TRIM(REGEXP_REPLACE(LOWER(title), '[^a-z0-9 ]+', ' '))
)
WHERE title_hash IS NULL;

-- Initial article_count_30d population. maintenance.py refreshes this nightly.
UPDATE sources s
LEFT JOIN (
  SELECT source_id, COUNT(*) AS n
  FROM articles
  WHERE fetched_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
  GROUP BY source_id
) c ON c.source_id = s.id
SET s.article_count_30d = COALESCE(c.n, 0);
