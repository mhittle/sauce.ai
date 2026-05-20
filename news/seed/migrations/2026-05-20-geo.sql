-- Article-level geographic resolution. The LLM classifier extracts a primary
-- place mention from each article; news/app/geo.py resolves it to a US
-- centroid (lat/lng) at classify time. Pre-existing rows stay NULL — radius
-- filtering skips them, country filtering still works via the existing
-- `country` column. `geo_place` keeps the LLM's free-text answer so the
-- ranking layer can show why an article matched.

ALTER TABLE article_features
  ADD COLUMN geo_lat   FLOAT DEFAULT NULL AFTER region,
  ADD COLUMN geo_lng   FLOAT DEFAULT NULL AFTER geo_lat,
  ADD COLUMN geo_place VARCHAR(120) DEFAULT NULL AFTER geo_lng,
  ADD KEY idx_feat_geo (geo_lat, geo_lng);
