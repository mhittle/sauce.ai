-- Casework/cabinetry classification on solicitations (PRD cabinet-relevance).
-- Folded into seed/schema.sql; apply to existing DBs.
ALTER TABLE solicitations ADD COLUMN IF NOT EXISTS cabinet_flag BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE solicitations ADD COLUMN IF NOT EXISTS cabinet_score NUMERIC(4,3);
ALTER TABLE solicitations ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_solicitations_cabinet ON solicitations (cabinet_flag, cabinet_score DESC);
