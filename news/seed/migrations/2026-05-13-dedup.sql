-- Migration: article deduplication (story_id + simhash).
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
-- Idempotent-ish: re-running will error on column-exists; ignore those errors.
--
-- For upgrades only. Fresh installs get these columns from schema.sql.

ALTER TABLE articles
  ADD COLUMN simhash  BIGINT UNSIGNED DEFAULT NULL AFTER title_hash,
  ADD COLUMN story_id BIGINT UNSIGNED DEFAULT NULL AFTER simhash,
  ADD KEY idx_articles_story (story_id, published_at);

-- Backfill: every legacy article is its own story.
UPDATE articles SET story_id = id WHERE story_id IS NULL;

-- simhash backfill is deferred to runtime: fetch_feeds will fill it for new
-- articles; legacy rows stay NULL and remain self-clustered. This is fine
-- because clustering only operates over a rolling 48h window.
