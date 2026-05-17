-- Article save / bookmark (roadmap Pri 6). Per-user saved articles.
-- folder defaults to 'Read Later' (v1 has no folder-management UI; the
-- column is the roadmap's table shape and forward-compat for v2 folders).
-- read_at is set when the user clicks through to a saved article from
-- /saved. Durability: jobs/maintenance.py excludes saved articles (and
-- their article_bodies) from the nightly retention prune, so a bookmark
-- keeps its reader-view copy readable indefinitely.
CREATE TABLE IF NOT EXISTS user_saves (
  user_id    INT UNSIGNED NOT NULL,
  article_id BIGINT UNSIGNED NOT NULL,
  folder     VARCHAR(64) NOT NULL DEFAULT 'Read Later',
  saved_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at    DATETIME DEFAULT NULL,
  PRIMARY KEY (user_id, article_id),
  KEY idx_saves_user_saved (user_id, saved_at),
  KEY idx_saves_article (article_id),
  CONSTRAINT fk_saves_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_saves_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
