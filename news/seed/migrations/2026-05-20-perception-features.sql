-- Adds 6 LLM-judged perceptual features + 6 rule-based structural features
-- to article_features, plus the matching feature_catalog rows. Existing rows
-- get the column DEFAULTs (0.5 for the LLM features = neutral midpoint; 0 for
-- the rule features = effectively no signal); they're not backfilled, but
-- classify_pending will populate the new columns on every newly-classified
-- article going forward.
--
-- Safe to run before deploy: existing user algorithms don't reference the new
-- feature keys, so build_score_sql ignores them until users opt in via /algo.

ALTER TABLE article_features
  ADD COLUMN tone_calmness         FLOAT NOT NULL DEFAULT 0.5 AFTER trending,
  ADD COLUMN sensationalism        FLOAT NOT NULL DEFAULT 0.5 AFTER tone_calmness,
  ADD COLUMN analysis_depth        FLOAT NOT NULL DEFAULT 0.5 AFTER sensationalism,
  ADD COLUMN emotional_charge      FLOAT NOT NULL DEFAULT 0.5 AFTER analysis_depth,
  ADD COLUMN hedging               FLOAT NOT NULL DEFAULT 0.5 AFTER emotional_charge,
  ADD COLUMN solution_orientation  FLOAT NOT NULL DEFAULT 0.5 AFTER hedging,
  ADD COLUMN headline_length       FLOAT NOT NULL DEFAULT 0   AFTER solution_orientation,
  ADD COLUMN caps_ratio            FLOAT NOT NULL DEFAULT 0   AFTER headline_length,
  ADD COLUMN punctuation_intensity FLOAT NOT NULL DEFAULT 0   AFTER caps_ratio,
  ADD COLUMN numeric_density       FLOAT NOT NULL DEFAULT 0   AFTER punctuation_intensity,
  ADD COLUMN question_headline     FLOAT NOT NULL DEFAULT 0   AFTER numeric_density,
  ADD COLUMN quote_present         FLOAT NOT NULL DEFAULT 0   AFTER question_headline;

INSERT INTO feature_catalog (feature_key, label, type, range_min, range_max, description, is_active, sort_order) VALUES
  ('tone_calmness',        'Tone (calm)',           'scale', 0, 1, 'LLM judgment: 1 = calm, measured; 0 = alarmist, urgent.',          1, 120),
  ('sensationalism',       'Sensationalism',        'scale', 0, 1, 'LLM judgment: 1 = sensational/clickbait phrasing; 0 = plain.',     1, 125),
  ('analysis_depth',       'Analysis depth',        'scale', 0, 1, 'LLM judgment: 1 = analytical/explainer; 0 = breaking-news brief.', 1, 130),
  ('emotional_charge',     'Emotional charge',      'scale', 0, 1, 'LLM judgment: 1 = emotionally loaded language; 0 = neutral.',      1, 135),
  ('hedging',              'Hedging',               'scale', 0, 1, 'LLM judgment: 1 = heavy hedging ("may", "could"); 0 = confident assertion.', 1, 140),
  ('solution_orientation', 'Solution orientation',  'scale', 0, 1, 'LLM judgment: 1 = solution-focused; 0 = problem-focused.',         1, 145),
  ('headline_length',      'Headline length',       'scale', 0, 1, 'Rule-based: normalized title word count, capped at 24.',           1, 150),
  ('caps_ratio',           'ALL-CAPS shouting',     'scale', 0, 1, 'Rule-based: uppercase letter ratio in title (shoutiness proxy).',  1, 155),
  ('punctuation_intensity','Punctuation intensity', 'scale', 0, 1, 'Rule-based: !? density per word in title+summary.',                1, 160),
  ('numeric_density',      'Data density',          'scale', 0, 1, 'Rule-based: digit-run density per word.',                          1, 165),
  ('question_headline',    'Question headline',     'scale', 0, 1, 'Rule-based: 1 if title ends with `?`, else 0.',                    1, 170),
  ('quote_present',        'Direct quote',          'scale', 0, 1, 'Rule-based: 1 if a direct quoted span appears in title or summary.', 1, 175);
