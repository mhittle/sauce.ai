-- Default feature catalog. Edit via /admin/features.

INSERT INTO feature_catalog (feature_key, label, type, range_min, range_max, description, is_active, sort_order) VALUES
  ('political_lean',       'Political lean',         'signed_scale', -1, 1, 'Article-level political lean. -1 = left, 0 = center, +1 = right.', 1, 10),
  ('source_lean',          'News source lean',       'signed_scale', -1, 1, 'Lean of the publication itself (lookup-based).', 1, 20),
  ('objectivity',          'Objectivity',            'scale',         0, 1, 'How factual vs. opinion-driven the piece appears.', 1, 30),
  ('reading_level',        'Reading level',          'scale',         0, 1, 'Normalized Flesch-Kincaid; higher = more advanced.', 1, 40),
  ('info_density',         'Information density',    'scale',         0, 1, 'Entity- and fact-density proxy from title+summary.', 1, 50),
  ('journalist_reputation','Journalist reputation',  'scale',         0, 1, 'Per-byline aggregate of source rep + tenure.', 1, 60),
  ('source_reputation',    'News source reputation', 'scale',         0, 1, 'Publication reputation from lookup table.', 1, 70),
  ('popularity',           'Popularity',             'scale',         0, 1, 'External signal from Reddit + HN today.', 1, 80),
  ('category',             'Category',               'categorical',   0, 0, 'politics / world / tech / business / science / sports / local / general', 1, 90),
  ('geography',            'Geography',              'categorical',   0, 0, 'Country and region of the source.', 1, 100),
  ('paywall',              'Paywall',                'scale',         0, 1, 'Per-article paywall score detected at classify time. 0 = free, 1 = subscription required, 0.5 = blocked/unknown.', 1, 110),
  ('trending',             'Trending',               'scale',         0, 1, 'How strongly the article matches a topic trending in the news at large (Google Trends + Google News RSS), refreshed by trending_poll. Opt-in (default weight 0); drives the Trending sort.', 1, 115);

-- Default presets used by the onboarding picker. Stored as JSON in a user_algorithms-like row template;
-- the app reads these constants from app/ranking.py PRESETS; no DB row needed.
