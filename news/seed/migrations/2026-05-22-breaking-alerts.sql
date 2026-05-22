-- Breaking-news email alerts: opt-in per-user prefs + per-event dedup log.
--
-- `user_alert_prefs` is deliberately a SEPARATE table from `users`
-- (rather than new columns on users) so a missing migration cannot
-- 500 the signed-in feed — only `/account/settings` and the new
-- /account/alerts/unsubscribe/<token> route read it, and both wrap
-- the SELECT in try/except. NOT BUG-007 class.
--
-- `breaking_news_alerts` is the per-event log; UNIQUE on `story_id`
-- enforces the "each story alerts at most once" guarantee (also
-- skipping LLM re-judgment of already-rejected stories on the next
-- 15-min tick).
CREATE TABLE IF NOT EXISTS user_alert_prefs (
  user_id          INT UNSIGNED NOT NULL,
  breaking_enabled TINYINT(1) NOT NULL DEFAULT 0,
  unsub_token      CHAR(40) NOT NULL DEFAULT '',
  alerts_day       DATE DEFAULT NULL,
  alerts_today     INT UNSIGNED NOT NULL DEFAULT 0,
  last_alert_at    DATETIME DEFAULT NULL,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  KEY idx_uap_enabled (breaking_enabled),
  CONSTRAINT fk_uap_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS breaking_news_alerts (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  story_id     BIGINT UNSIGNED NOT NULL,
  outlet_count INT UNSIGNED NOT NULL DEFAULT 0,
  status       ENUM('sent','rejected') NOT NULL,
  headline     VARCHAR(200) NOT NULL DEFAULT '',
  blurb        VARCHAR(500) NOT NULL DEFAULT '',
  recipients   INT UNSIGNED NOT NULL DEFAULT 0,
  detected_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_bna_story (story_id),
  KEY idx_bna_status_detected (status, detected_at),
  CONSTRAINT fk_bna_story FOREIGN KEY (story_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
