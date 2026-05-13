-- Migration: add article_bodies table for in-app reader view.
-- Run via phpMyAdmin -> SQL tab against the lt1ih6uyy2z6_news database.
--
-- Body text is stored separately from `articles` so the main table stays
-- lean (the feed query joins it heavily). 30-day retention is pruned
-- nightly by jobs/maintenance.py — bookmarked articles get longer
-- retention once /saved ships (see roadmap).
--
-- Fresh installs get this table from schema.sql.

CREATE TABLE IF NOT EXISTS article_bodies (
  article_id  BIGINT UNSIGNED NOT NULL,
  body_text   MEDIUMTEXT,
  body_html   MEDIUMTEXT,
  lead_image  VARCHAR(1000) DEFAULT NULL,
  author      VARCHAR(300) DEFAULT NULL,
  word_count  INT UNSIGNED NOT NULL DEFAULT 0,
  extractor   VARCHAR(32) NOT NULL DEFAULT 'trafilatura',
  status      ENUM('ok','empty','blocked','error') NOT NULL DEFAULT 'ok',
  extracted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (article_id),
  KEY idx_bodies_extracted (extracted_at),
  CONSTRAINT fk_bodies_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
