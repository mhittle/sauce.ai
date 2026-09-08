-- Claim (health-headline reality check): cached checks keyed by feed
-- article or pasted-URL hash. The /claim route catches a missing-table
-- ProgrammingError and still renders the card (without a permalink), so
-- a late migration never 500s. NOT BUG-007 class.
CREATE TABLE IF NOT EXISTS claim_checks (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  article_id    BIGINT UNSIGNED NULL,
  url_hash      CHAR(64) NULL,
  input_kind    ENUM('article','url','text') NOT NULL DEFAULT 'url',
  headline      VARCHAR(500) NOT NULL DEFAULT '',
  source_url    VARCHAR(2000) NULL,
  claim_json    MEDIUMTEXT NOT NULL,
  study_json    MEDIUMTEXT NOT NULL,
  numbers_json  TEXT NOT NULL,
  flags_json    TEXT NOT NULL,
  grade         TINYINT UNSIGNED NOT NULL DEFAULT 5,
  status        ENUM('ok','no-study','llm-unavailable','error') NOT NULL DEFAULT 'ok',
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_claim_url (url_hash),
  KEY idx_claim_article (article_id),
  KEY idx_claim_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
