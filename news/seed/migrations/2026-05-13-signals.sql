-- Migration: add user_signals + user_source_prefs.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database
-- before deploying the thumbs-up/down feature.
--
-- Fresh installs get both tables from schema.sql.

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
