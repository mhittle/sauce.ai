-- Per-algorithm keyword mute & boost. Lives next to the per-user
-- `user_term_prefs` table (PR #77): same mute/boost model and same
-- pure SQL builder (`app.term_prefs.build_term_clauses`), but scoped to
-- a single `user_algorithms` row so different saved profiles can carry
-- different keyword intent ("Morning brief" boosts AI/local tech;
-- "Weekend deep-dive" mutes politics).
--
-- routes/feed.py reads this table for the signed-in user's ACTIVE
-- algorithm on every feed load and merges the rows with user_term_prefs
-- before calling the shared builder, so apply this migration BEFORE
-- deploying the code (BUG-007 class: a missing table 500s the signed-in
-- feed). Anonymous visitors / `/firehose` / digest are unaffected.

CREATE TABLE IF NOT EXISTS algorithm_term_prefs (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  algorithm_id INT UNSIGNED NOT NULL,
  term         VARCHAR(128) NOT NULL,
  mode         ENUM('mute','boost') NOT NULL,
  weight       FLOAT NOT NULL DEFAULT 1.5,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_algo_term (algorithm_id, term),
  KEY idx_algo_term_algo (algorithm_id),
  CONSTRAINT fk_algo_term_algo FOREIGN KEY (algorithm_id)
    REFERENCES user_algorithms (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
