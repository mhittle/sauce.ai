-- Shareable algorithm gallery (roadmap Pri 8 — "Shareable algorithm gallery").
-- A signed-in user can publish a snapshot of their active algorithm to
-- `shared_algorithms`; other users browse /gallery and adopt = clone the
-- snapshot into a new active row in their own `user_algorithms`. Every
-- adopt writes one `algorithm_adoptions` row, which feeds the three v1
-- usage stats surfaced on the listing (total / last-7d / active).
--
-- Tables are read-only at feed time (only /gallery and its publish/adopt
-- POSTs touch them), so a missing table does NOT 500 the signed-in feed
-- — unlike user_term_prefs (BUG-007 class). Routes guard against the
-- missing-table case implicitly by being on /gallery only.

CREATE TABLE IF NOT EXISTS shared_algorithms (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  owner_id      INT UNSIGNED NOT NULL,
  name          VARCHAR(120) NOT NULL,
  description   VARCHAR(500) NOT NULL DEFAULT '',
  weights_json  TEXT NOT NULL,                    -- snapshot at publish time
  is_public     TINYINT(1) NOT NULL DEFAULT 1,    -- admin/owner can hide
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sa_owner (owner_id),
  KEY idx_sa_public_created (is_public, created_at),
  CONSTRAINT fk_sa_owner FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS algorithm_adoptions (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  shared_algorithm_id BIGINT UNSIGNED NOT NULL,
  user_id             INT UNSIGNED NOT NULL,
  -- Points at the cloned-into row in user_algorithms; NULL once the user
  -- deletes that profile, which is the signal we use to compute "active
  -- adoptions" (count distinct users where this is still set).
  user_algorithm_id   INT UNSIGNED DEFAULT NULL,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_aa_shared_created (shared_algorithm_id, created_at),
  KEY idx_aa_user (user_id),
  KEY idx_aa_active (shared_algorithm_id, user_algorithm_id),
  CONSTRAINT fk_aa_shared FOREIGN KEY (shared_algorithm_id)
    REFERENCES shared_algorithms (id) ON DELETE CASCADE,
  CONSTRAINT fk_aa_user FOREIGN KEY (user_id)
    REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_aa_user_algo FOREIGN KEY (user_algorithm_id)
    REFERENCES user_algorithms (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
