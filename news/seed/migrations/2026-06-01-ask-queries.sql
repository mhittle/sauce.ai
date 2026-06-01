-- Ask your feed (grounded conversational news): one row per submitted
-- question. Carries the persistent daily-cap counter (a COUNT() over
-- created_at >= UTC midnight, which scales fine for a 25/day cap) and
-- doubles as conversation history + audit.
--
-- Deliberately a SEPARATE table from `users`, so a missing migration
-- cannot 500 the signed-in feed. The /ask route catches a missing-table
-- ProgrammingError and falls back to an in-process daily limiter — the
-- page still works pre-migration. NOT BUG-007 class.
CREATE TABLE IF NOT EXISTS ask_queries (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id       INT UNSIGNED NOT NULL,
  conversation  CHAR(40) NOT NULL DEFAULT '',
  question      VARCHAR(2000) NOT NULL,
  answered      TINYINT(1) NOT NULL DEFAULT 0,
  article_ids   VARCHAR(500) NOT NULL DEFAULT '',
  answer_text   TEXT NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ask_user_day (user_id, created_at),
  KEY idx_ask_convo (conversation),
  CONSTRAINT fk_ask_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
