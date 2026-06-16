-- AI cross-validation toggle (org-wide). When enabled, takeoff extraction
-- also runs through a secondary OpenAI vision model and disagreements lower
-- the primary (Anthropic) line confidence so they surface for human review.
ALTER TABLE org_settings
  ADD COLUMN IF NOT EXISTS cross_validation_enabled boolean NOT NULL DEFAULT false;
