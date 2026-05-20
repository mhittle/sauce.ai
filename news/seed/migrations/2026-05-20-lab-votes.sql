-- Anonymous up/down votes for "Coming soon" product concepts on the
-- root-domain lab landing page (https://sauce.ai/). One row per
-- (concept_key, voter_token) pair; voter_token is a 40-hex random
-- value stored in the per-browser `lab_voter_token` cookie. NOT
-- BUG-007 class: only the /labvotes/* endpoints touch this table, so
-- a missing migration only 500s those endpoints (and the landing
-- page's JS hides the vote UI quietly). The rest of the news app is
-- unaffected.
CREATE TABLE IF NOT EXISTS lab_concept_votes (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  concept_key  VARCHAR(64) NOT NULL,
  voter_token  CHAR(40) NOT NULL,
  vote         TINYINT NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_concept_voter (concept_key, voter_token),
  KEY idx_concept (concept_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
