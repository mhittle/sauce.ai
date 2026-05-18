-- Keyword / topic mute & boost (roadmap Pri 8).
-- Per-user term lists applied at the reader-feed query layer:
--   mode='mute'  -> hard-filter articles whose title+summary contains term
--   mode='boost' -> multiply a matching article's score by `weight`
-- routes/feed.py reads this table for every signed-in feed load, so apply
-- this migration BEFORE deploying the code (BUG-007 class: a missing
-- table 500s the signed-in feed). Anonymous visitors are unaffected.

CREATE TABLE IF NOT EXISTS user_term_prefs (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED NOT NULL,
  term       VARCHAR(128) NOT NULL,
  mode       ENUM('mute','boost') NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.5,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_term_pref (user_id, term),
  KEY idx_term_pref_user (user_id),
  CONSTRAINT fk_term_pref_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
