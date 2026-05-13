-- 2026-05-13 — User-added RSS feed subscriptions
--
-- Adds `owner_id` to `sources` so a user can paste an RSS URL and have it
-- added to their personal feed pool. NULL = global pool (current behavior
-- for all existing rows). Non-null = personal source visible only to that
-- user's `/`, `/firehose`, and any other reader-facing queries.
--
-- fetch_feeds.py picks up all active sources regardless of owner — one
-- source, one fetch — so the cron pipeline is unchanged. Per-user
-- visibility is enforced at query time in the route layer.

ALTER TABLE sources
  ADD COLUMN owner_id INT UNSIGNED DEFAULT NULL AFTER region,
  ADD KEY idx_sources_owner (owner_id),
  ADD CONSTRAINT fk_sources_owner FOREIGN KEY (owner_id)
    REFERENCES users (id) ON DELETE CASCADE;
