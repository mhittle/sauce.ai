-- News aggregator schema (MySQL 5.7+)
-- Run once via phpMyAdmin against the target DB.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS users (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  email         VARCHAR(255) NOT NULL,
  password_hash VARBINARY(255) NOT NULL,
  is_admin      TINYINT(1) NOT NULL DEFAULT 0,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
  sid        CHAR(64) NOT NULL,
  user_id    INT UNSIGNED NOT NULL,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (sid),
  KEY idx_sessions_user (user_id),
  KEY idx_sessions_exp (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sources (
  id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name              VARCHAR(200) NOT NULL,
  feed_url          VARCHAR(500) NOT NULL,
  homepage          VARCHAR(500) DEFAULT NULL,
  source_lean       FLOAT NOT NULL DEFAULT 0,        -- -1..+1
  source_reputation FLOAT NOT NULL DEFAULT 0.5,      -- 0..1
  category          VARCHAR(64) NOT NULL DEFAULT 'general',
  country           VARCHAR(8) NOT NULL DEFAULT 'US',
  region            VARCHAR(64) NOT NULL DEFAULT 'national',
  article_count_30d INT UNSIGNED NOT NULL DEFAULT 0, -- refreshed by maintenance.py
  is_active         TINYINT(1) NOT NULL DEFAULT 1,
  last_fetched_at   DATETIME DEFAULT NULL,
  last_status       VARCHAR(32) DEFAULT NULL,
  last_error        TEXT,
  error_count       INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sources_feed (feed_url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS articles (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id     INT UNSIGNED NOT NULL,
  url           VARCHAR(1000) NOT NULL,
  url_hash      CHAR(40) NOT NULL,
  title         VARCHAR(500) NOT NULL,
  title_hash    CHAR(40) DEFAULT NULL,  -- sha1 of normalized title; null on legacy rows
  summary       TEXT,
  thumbnail_url VARCHAR(1000) DEFAULT NULL,
  byline        VARCHAR(300) DEFAULT NULL,
  published_at  DATETIME NOT NULL,
  fetched_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status        ENUM('pending','classified','failed') NOT NULL DEFAULT 'pending',
  PRIMARY KEY (id),
  UNIQUE KEY uk_articles_url (url_hash),
  KEY idx_articles_pub (published_at),
  KEY idx_articles_status (status),
  KEY idx_articles_source_pub (source_id, published_at),
  KEY idx_articles_title_hash (title_hash, fetched_at),
  CONSTRAINT fk_articles_source FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article_features (
  article_id            BIGINT UNSIGNED NOT NULL,
  political_lean        FLOAT NOT NULL DEFAULT 0,   -- -1..+1
  reading_level         FLOAT NOT NULL DEFAULT 0,   -- 0..1 normalized
  objectivity           FLOAT NOT NULL DEFAULT 0.5, -- 0..1
  info_density          FLOAT NOT NULL DEFAULT 0,   -- 0..1
  journalist_reputation FLOAT NOT NULL DEFAULT 0.5, -- 0..1
  source_lean           FLOAT NOT NULL DEFAULT 0,
  source_reputation     FLOAT NOT NULL DEFAULT 0.5,
  category              VARCHAR(64) NOT NULL DEFAULT 'general',
  country               VARCHAR(8) NOT NULL DEFAULT 'US',
  region                VARCHAR(64) NOT NULL DEFAULT 'national',
  popularity            FLOAT NOT NULL DEFAULT 0,   -- 0..1
  story_obscurity       FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = only-this-story
  source_obscurity      FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = tiny/unknown source
  paywall               FLOAT NOT NULL DEFAULT 0,   -- 0..1, 1 = subscription-required
  classifier_version    VARCHAR(32) NOT NULL DEFAULT 'v1',
  classified_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (article_id),
  KEY idx_feat_lean (political_lean),
  KEY idx_feat_obj (objectivity),
  KEY idx_feat_cat (category),
  CONSTRAINT fk_features_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS journalists (
  id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
  normalized_name     VARCHAR(200) NOT NULL,
  display_name        VARCHAR(200) NOT NULL,
  first_seen_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  article_count       INT UNSIGNED NOT NULL DEFAULT 0,
  computed_reputation FLOAT NOT NULL DEFAULT 0.5,
  PRIMARY KEY (id),
  UNIQUE KEY uk_journ_norm (normalized_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article_journalists (
  article_id    BIGINT UNSIGNED NOT NULL,
  journalist_id INT UNSIGNED NOT NULL,
  PRIMARY KEY (article_id, journalist_id),
  KEY idx_aj_journ (journalist_id),
  CONSTRAINT fk_aj_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
  CONSTRAINT fk_aj_journ FOREIGN KEY (journalist_id) REFERENCES journalists (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS popularity_signals (
  article_id BIGINT UNSIGNED NOT NULL,
  source     VARCHAR(16) NOT NULL,         -- 'reddit' | 'hn'
  score      INT NOT NULL DEFAULT 0,
  comments   INT NOT NULL DEFAULT 0,
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (article_id, source),
  CONSTRAINT fk_pop_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_algorithms (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id         INT UNSIGNED NOT NULL,
  name            VARCHAR(120) NOT NULL,
  weights_json    TEXT NOT NULL,
  expression_text TEXT,
  is_active       TINYINT(1) NOT NULL DEFAULT 0,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ua_user (user_id, is_active),
  CONSTRAINT fk_ua_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_clicks (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED DEFAULT NULL,
  article_id BIGINT UNSIGNED NOT NULL,
  ts         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_clicks_article (article_id),
  KEY idx_clicks_user_ts (user_id, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Generic per-user signal stream. Sized to carry the full Signal Learning
-- vocabulary: thumb_up, thumb_down, save, share, hide, dwell_ms, scroll_pct,
-- return_click. `value` is NULL for binary signals and numeric for the
-- magnitude-bearing ones. Binary signals are unique per (user, article, type)
-- so toggling is a simple INSERT/DELETE.
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

-- Per-user-source preference. Missing row = default weight 1.0. weight=0
-- means hidden (filtered out of feed). Anything between 0 and 1 downweights
-- the source in the score expression.
CREATE TABLE IF NOT EXISTS user_source_prefs (
  user_id    INT UNSIGNED NOT NULL,
  source_id  INT UNSIGNED NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, source_id),
  CONSTRAINT fk_usp_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_usp_source FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feature_catalog (
  feature_key VARCHAR(64) NOT NULL,
  label       VARCHAR(120) NOT NULL,
  type        ENUM('scale','signed_scale','binary','categorical') NOT NULL,
  range_min   FLOAT NOT NULL DEFAULT 0,
  range_max   FLOAT NOT NULL DEFAULT 1,
  description TEXT,
  is_active   TINYINT(1) NOT NULL DEFAULT 1,
  sort_order  INT NOT NULL DEFAULT 100,
  PRIMARY KEY (feature_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pipeline_log (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job        VARCHAR(64) NOT NULL,
  level      VARCHAR(16) NOT NULL DEFAULT 'info',
  message    TEXT,
  ts         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_log_job_ts (job, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS llm_usage (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  model           VARCHAR(64) NOT NULL,
  input_tokens    INT UNSIGNED NOT NULL DEFAULT 0,
  output_tokens   INT UNSIGNED NOT NULL DEFAULT 0,
  cache_read_tokens INT UNSIGNED NOT NULL DEFAULT 0,
  articles        INT UNSIGNED NOT NULL DEFAULT 0,
  est_cost_usd    DECIMAL(10,5) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_llm_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
