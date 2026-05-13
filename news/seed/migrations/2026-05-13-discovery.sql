-- Migration: add candidate_sources for automated source discovery.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database
-- before deploying the discover_harvest / discover_llm / discover_promote
-- cron jobs. Fresh installs get the table from schema.sql.

CREATE TABLE IF NOT EXISTS candidate_sources (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  domain        VARCHAR(255) NOT NULL,
  feed_url      VARCHAR(1024) DEFAULT NULL,
  name          VARCHAR(255) DEFAULT NULL,
  homepage_url  VARCHAR(1024) DEFAULT NULL,
  category      VARCHAR(64) DEFAULT NULL,
  score         INT NOT NULL DEFAULT 0,
  first_seen_via VARCHAR(32) NOT NULL,
  last_seen_via  VARCHAR(32) NOT NULL,
  first_seen_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  state         ENUM('pending','validated','approved','rejected','blacklisted')
                NOT NULL DEFAULT 'pending',
  reject_reason VARCHAR(255) DEFAULT NULL,
  validation_attempted_at DATETIME DEFAULT NULL,
  validation_error VARCHAR(255) DEFAULT NULL,
  promoted_source_id INT UNSIGNED DEFAULT NULL,
  notes         TEXT,
  PRIMARY KEY (id),
  UNIQUE KEY uk_candidate_domain (domain),
  KEY idx_candidate_state_score (state, score),
  KEY idx_candidate_last_seen (last_seen_at),
  CONSTRAINT fk_candidate_source FOREIGN KEY (promoted_source_id)
    REFERENCES sources (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
