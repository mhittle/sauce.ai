-- News aggregator schema (MySQL 5.7+)
-- Run once via phpMyAdmin against the target DB.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS users (
  id                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  email                VARCHAR(255) NOT NULL,
  password_hash        VARBINARY(255) NOT NULL,
  is_admin             TINYINT(1) NOT NULL DEFAULT 0,
  created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  digest_enabled       TINYINT(1) NOT NULL DEFAULT 0,
  digest_unsub_token   CHAR(40) NOT NULL DEFAULT '',
  digest_last_sent_at  DATETIME DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_email (email),
  KEY idx_users_digest (digest_enabled, digest_last_sent_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
  sid        CHAR(64) NOT NULL,
  user_id    INT UNSIGNED NOT NULL,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (sid),
  KEY idx_sessions_user (user_id),
  KEY idx_sessions_exp (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sources (
  id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name              VARCHAR(200) NOT NULL,
  feed_url          VARCHAR(500) NOT NULL,
  homepage          VARCHAR(500) DEFAULT NULL,
  source_lean       FLOAT NOT NULL DEFAULT 0,        -- -1..+1
  source_reputation FLOAT NOT NULL DEFAULT 0.5,      -- 0..1
  category          VARCHAR(64) NOT NULL DEFAULT 'general',
  country           VARCHAR(8) NOT NULL DEFAULT 'US',
  region            VARCHAR(64) NOT NULL DEFAULT 'national',
  owner_id          INT UNSIGNED DEFAULT NULL,        -- NULL = global pool; non-null = user-added personal source
  article_count_30d INT UNSIGNED NOT NULL DEFAULT 0, -- refreshed by maintenance.py
  is_active         TINYINT(1) NOT NULL DEFAULT 1,
  last_fetched_at   DATETIME DEFAULT NULL,
  last_status       VARCHAR(32) DEFAULT NULL,
  last_error        TEXT,
  error_count       INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sources_feed (feed_url),
  KEY idx_sources_owner (owner_id),
  CONSTRAINT fk_sources_owner FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS articles (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_id     INT UNSIGNED NOT NULL,
  url           VARCHAR(1000) NOT NULL,
  url_hash      CHAR(40) NOT NULL,
  title         VARCHAR(500) NOT NULL,
  title_hash    CHAR(40) DEFAULT NULL,  -- sha1 of normalized title; null on legacy rows
  simhash       BIGINT UNSIGNED DEFAULT NULL,  -- 64-bit simhash over title + summary lead
  story_id      BIGINT UNSIGNED DEFAULT NULL,  -- cluster id = canonical member's articles.id
  summary       TEXT,
  thumbnail_url VARCHAR(1000) DEFAULT NULL,
  byline        VARCHAR(300) DEFAULT NULL,
  published_at  DATETIME NOT NULL,
  fetched_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status        ENUM('pending','classified','failed') NOT NULL DEFAULT 'pending',
  PRIMARY KEY (id),
  UNIQUE KEY uk_articles_url (url_hash),
  KEY idx_articles_pub (published_at),
  KEY idx_articles_status (status),
  KEY idx_articles_source_pub (source_id, published_at),
  KEY idx_articles_title_hash (title_hash, fetched_at),
  KEY idx_articles_story (story_id, published_at),
  FULLTEXT KEY ft_articles_search (title, summary),
  CONSTRAINT fk_articles_source FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article_features (
  article_id            BIGINT UNSIGNED NOT NULL,
  political_lean        FLOAT NOT NULL DEFAULT 0,   -- -1..+1
  reading_level         FLOAT NOT NULL DEFAULT 0,   -- 0..1 normalized
  objectivity           FLOAT NOT NULL DEFAULT 0.5, -- 0..1
  info_density          FLOAT NOT NULL DEFAULT 0,   -- 0..1
  journalist_reputation FLOAT NOT NULL DEFAULT 0.5, -- 0..1
  source_lean           FLOAT NOT NULL DEFAULT 0,
  source_reputation     FLOAT NOT NULL DEFAULT 0.5,
  category              VARCHAR(64) NOT NULL DEFAULT 'general',
  country               VARCHAR(8) NOT NULL DEFAULT 'US',
  region                VARCHAR(64) NOT NULL DEFAULT 'national',
  geo_lat               FLOAT DEFAULT NULL,         -- LLM-extracted place centroid; NULL = unresolved
  geo_lng               FLOAT DEFAULT NULL,
  geo_place             VARCHAR(120) DEFAULT NULL,  -- raw place string the LLM returned
  popularity            FLOAT NOT NULL DEFAULT 0,   -- 0..1
  story_obscurity       FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = only-this-story
  source_obscurity      FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = tiny/unknown source
  paywall               FLOAT NOT NULL DEFAULT 0,   -- 0..1, 1 = subscription-required
  trending              FLOAT NOT NULL DEFAULT 0,   -- 0..1, external trending-topic match (trending_poll)
  -- 6 LLM-judged perceptual features (Haiku, batched with political_lean/objectivity):
  tone_calmness         FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = calm/measured, 0 = alarmist
  sensationalism        FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = clickbait/sensational, 0 = plain
  analysis_depth        FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = analytical/explainer, 0 = brief
  emotional_charge      FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = emotionally loaded, 0 = neutral
  hedging               FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = heavy hedging, 0 = confident
  solution_orientation  FLOAT NOT NULL DEFAULT 0.5, -- 0..1, 1 = solution-focused, 0 = problem-focused
  -- 6 rule-based structural features (deterministic, no LLM cost):
  headline_length       FLOAT NOT NULL DEFAULT 0,   -- 0..1, normalized title word count
  caps_ratio            FLOAT NOT NULL DEFAULT 0,   -- 0..1, uppercase ratio in title
  punctuation_intensity FLOAT NOT NULL DEFAULT 0,   -- 0..1, !? density per word
  numeric_density       FLOAT NOT NULL DEFAULT 0,   -- 0..1, digit-run density per word
  question_headline     FLOAT NOT NULL DEFAULT 0,   -- 0/1, title ends with `?`
  quote_present         FLOAT NOT NULL DEFAULT 0,   -- 0/1, direct quote in title or summary
  classifier_version    VARCHAR(32) NOT NULL DEFAULT 'v1',
  classified_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (article_id),
  KEY idx_feat_lean (political_lean),
  KEY idx_feat_obj (objectivity),
  KEY idx_feat_cat (category),
  KEY idx_feat_geo (geo_lat, geo_lng),
  CONSTRAINT fk_features_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article_bodies (
  article_id   BIGINT UNSIGNED NOT NULL,
  body_text    MEDIUMTEXT,
  body_html    MEDIUMTEXT,
  lead_image   VARCHAR(1000) DEFAULT NULL,
  author       VARCHAR(300) DEFAULT NULL,
  word_count   INT UNSIGNED NOT NULL DEFAULT 0,
  extractor    VARCHAR(32) NOT NULL DEFAULT 'trafilatura',
  status       ENUM('ok','empty','blocked','error') NOT NULL DEFAULT 'ok',
  extracted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (article_id),
  KEY idx_bodies_extracted (extracted_at),
  CONSTRAINT fk_bodies_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS journalists (
  id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
  normalized_name     VARCHAR(200) NOT NULL,
  display_name        VARCHAR(200) NOT NULL,
  first_seen_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  article_count       INT UNSIGNED NOT NULL DEFAULT 0,
  computed_reputation FLOAT NOT NULL DEFAULT 0.5,
  PRIMARY KEY (id),
  UNIQUE KEY uk_journ_norm (normalized_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article_journalists (
  article_id    BIGINT UNSIGNED NOT NULL,
  journalist_id INT UNSIGNED NOT NULL,
  PRIMARY KEY (article_id, journalist_id),
  KEY idx_aj_journ (journalist_id),
  CONSTRAINT fk_aj_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
  CONSTRAINT fk_aj_journ FOREIGN KEY (journalist_id) REFERENCES journalists (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS popularity_signals (
  article_id BIGINT UNSIGNED NOT NULL,
  source     VARCHAR(16) NOT NULL,         -- 'reddit' | 'hn'
  score      INT NOT NULL DEFAULT 0,
  comments   INT NOT NULL DEFAULT 0,
  permalink  VARCHAR(1024) DEFAULT NULL,   -- discussion thread URL (Techmeme-style)
  subreddit  VARCHAR(64) DEFAULT NULL,     -- e.g. 'technology'; NULL for hn
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (article_id, source),
  CONSTRAINT fk_pop_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_algorithms (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id         INT UNSIGNED NOT NULL,
  name            VARCHAR(120) NOT NULL,
  weights_json    TEXT NOT NULL,
  expression_text TEXT,
  is_active       TINYINT(1) NOT NULL DEFAULT 0,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ua_user (user_id, is_active),
  CONSTRAINT fk_ua_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_clicks (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id    INT UNSIGNED DEFAULT NULL,
  article_id BIGINT UNSIGNED NOT NULL,
  ts         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_clicks_article (article_id),
  KEY idx_clicks_user_ts (user_id, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Generic per-user signal stream. Sized to carry the full Signal Learning
-- vocabulary: thumb_up, thumb_down, save, share, hide, dwell_ms, scroll_pct,
-- return_click. `value` is NULL for binary signals and numeric for the
-- magnitude-bearing ones. Binary signals are unique per (user, article, type)
-- so toggling is a simple INSERT/DELETE.
CREATE TABLE IF NOT EXISTS user_signals (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  signal_type VARCHAR(32) NOT NULL,
  value       FLOAT DEFAULT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_signal_binary (user_id, article_id, signal_type),
  KEY idx_signal_user_type_ts (user_id, signal_type, created_at),
  KEY idx_signal_article_type (article_id, signal_type),
  CONSTRAINT fk_signal_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_signal_article FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-user-source preference. Missing row = default weight 1.0. weight=0
-- means hidden (filtered out of feed). Anything between 0 and 1 downweights
-- the source in the score expression.
CREATE TABLE IF NOT EXISTS user_source_prefs (
  user_id    INT UNSIGNED NOT NULL,
  source_id  INT UNSIGNED NOT NULL,
  weight     FLOAT NOT NULL DEFAULT 1.0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, source_id),
  CONSTRAINT fk_usp_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_usp_source FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-user saved articles (bookmarks). folder defaults to 'Read Later'
-- (no folder-management UI in v1; column is forward-compat for v2).
-- read_at is set on click-through from /saved. Durability: maintenance.py
-- excludes saved articles (and their article_bodies) from the retention
-- prune, so a saved article's reader-view copy stays readable indefinitely.
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

-- Per-algorithm keyword mute & boost. `mode='mute'` hard-filters any
-- article whose title+summary contains `term`; `mode='boost'` multiplies
-- a matching article's score by `weight` (the strongest matching boost
-- wins; boosts don't compound). Scoped to one `user_algorithms` row so
-- different saved profiles carry their own keyword intent.
-- `routes/feed.py` reads this for the active algorithm and feeds the
-- rows into `app.term_prefs.build_term_clauses` (the builder already
-- dedupes terms and lets mute beat boost).
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
  CONSTRAINT fk_algo_term_algo FOREIGN KEY (algorithm_id) REFERENCES user_algorithms (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Automated source-discovery candidate pool. One row per unknown domain
-- surfaced by `jobs/discover_harvest.py` (Reddit/HN), `discover_llm.py`
-- (Claude suggestions), or future social-firehose jobs. `score` is the
-- raw hit count; `state` advances pending → validated (after
-- discover_promote attaches a feed_url) → approved/rejected/blacklisted
-- by an admin on /admin/discovery. `promoted_source_id` back-links to
-- the sources row created on approval. Blacklisted domains are sticky:
-- discover_harvest skips them so a noisy outlet can't keep coming back.
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

-- Cached LLM-generated framing summary for a deduplicated story cluster.
-- Keyed by canonical articles.id (= story_id). member_signature is sha1 of
-- the sorted member-id list; when the cluster gains/loses members, the
-- signature changes and the dossier route regenerates the summary lazily.
CREATE TABLE IF NOT EXISTS story_dossiers (
  story_id         BIGINT UNSIGNED NOT NULL,
  member_signature CHAR(40) NOT NULL,
  summary_text     TEXT NOT NULL,
  article_count    INT UNSIGNED NOT NULL DEFAULT 0,
  lean_buckets     VARCHAR(16) NOT NULL DEFAULT '',
  model            VARCHAR(64) NOT NULL DEFAULT '',
  generated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (story_id),
  CONSTRAINT fk_dossier_story FOREIGN KEY (story_id) REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Trending topics snapshot for the /trending page. `trending_poll`
-- rebuilds both tables in full every tick from the Google Trends/News
-- topic index (the same index that drives the feed's Trending sort);
-- stale topics simply don't reappear, so no separate decay job is
-- needed. topic_key = sha1 of the topic's sorted significant tokens, so
-- near-duplicate headlines collapse into one row. No FK on topic_key
-- (the writer owns both tables and replaces them atomically each tick);
-- the article FK cascades so pruned articles drop their match rows.
CREATE TABLE IF NOT EXISTS trending_topics (
  topic_key   CHAR(40) NOT NULL,
  label       VARCHAR(255) NOT NULL,
  origin      VARCHAR(16) NOT NULL DEFAULT '',   -- 'trends' | 'gnews'
  heat        FLOAT NOT NULL DEFAULT 0,          -- 0..1 latest snapshot heat
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (topic_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS trending_topic_articles (
  topic_key   CHAR(40) NOT NULL,
  article_id  BIGINT UNSIGNED NOT NULL,
  match_score FLOAT NOT NULL DEFAULT 0,          -- 0..1 per-topic match
  PRIMARY KEY (topic_key, article_id),
  KEY idx_tta_article (article_id),
  CONSTRAINT fk_tta_article FOREIGN KEY (article_id)
    REFERENCES articles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feature_catalog (
  feature_key VARCHAR(64) NOT NULL,
  label       VARCHAR(120) NOT NULL,
  type        ENUM('scale','signed_scale','binary','categorical') NOT NULL,
  range_min   FLOAT NOT NULL DEFAULT 0,
  range_max   FLOAT NOT NULL DEFAULT 1,
  description TEXT,
  is_active   TINYINT(1) NOT NULL DEFAULT 1,
  sort_order  INT NOT NULL DEFAULT 100,
  PRIMARY KEY (feature_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pipeline_log (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job        VARCHAR(64) NOT NULL,
  level      VARCHAR(16) NOT NULL DEFAULT 'info',
  message    TEXT,
  ts         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_log_job_ts (job, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS llm_usage (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  model           VARCHAR(64) NOT NULL,
  input_tokens    INT UNSIGNED NOT NULL DEFAULT 0,
  output_tokens   INT UNSIGNED NOT NULL DEFAULT 0,
  cache_read_tokens INT UNSIGNED NOT NULL DEFAULT 0,
  articles        INT UNSIGNED NOT NULL DEFAULT 0,
  est_cost_usd    DECIMAL(10,5) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_llm_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Shareable algorithm gallery: published snapshots of `user_algorithms`
-- + the per-adoption event log. See migrations/2026-05-20-shared-algorithms.sql.
CREATE TABLE IF NOT EXISTS shared_algorithms (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  owner_id      INT UNSIGNED NOT NULL,
  name          VARCHAR(120) NOT NULL,
  description   VARCHAR(500) NOT NULL DEFAULT '',
  weights_json  TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  is_public     TINYINT(1) NOT NULL DEFAULT 1,
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

-- Anonymous up/down votes for "Coming soon" product concepts on the
-- root-domain lab landing page (https://sauce.ai/). See
-- migrations/2026-05-20-lab-votes.sql.
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
