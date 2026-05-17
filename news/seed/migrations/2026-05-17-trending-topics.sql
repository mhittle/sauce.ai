-- Migration: trending-topics snapshot tables for the /trending page.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
-- Idempotent: CREATE TABLE IF NOT EXISTS is safe to re-run.
--
-- Fresh installs get these from schema.sql.
--
-- The existing `trending_poll` cron (every 30 min, already scheduled)
-- fills both tables on its next tick once this is applied — no new cron
-- entry and no backfill step. Until applied, /trending 500s on the
-- missing tables; the feed's Trending *sort* (article_features.trending)
-- is unaffected.

CREATE TABLE IF NOT EXISTS trending_topics (
  topic_key   CHAR(40) NOT NULL,
  label       VARCHAR(255) NOT NULL,
  origin      VARCHAR(16) NOT NULL DEFAULT '',   -- 'trends' | 'gnews'
  heat        FLOAT NOT NULL DEFAULT 0,          -- 0..1 latest snapshot heat
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (topic_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS trending_topic_articles (
  topic_key   CHAR(40) NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  match_score FLOAT NOT NULL DEFAULT 0,          -- 0..1 per-topic match
  PRIMARY KEY (topic_key, article_id),
  KEY idx_tta_article (article_id),
  CONSTRAINT fk_tta_article FOREIGN KEY (article_id)
    REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
