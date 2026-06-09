-- Bid/plans track: Solicitation + documents (PRD PlanHub model).
-- Folded into seed/schema.sql; apply to existing DBs that predate it.
CREATE TABLE IF NOT EXISTS solicitations (
    id                  BIGSERIAL PRIMARY KEY,
    source_type         TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    title               TEXT,
    agency              TEXT,
    description         TEXT,
    naics               TEXT,
    category            TEXT,
    state               TEXT,
    place_city          TEXT,
    estimated_value     NUMERIC(14,2),
    posted_date         DATE,
    due_date            DATE,
    status              TEXT,
    source_url          TEXT,
    geom                geometry(Point, 4326),
    project_id          BIGINT REFERENCES projects(id),
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_solicitations_due ON solicitations (due_date);
CREATE INDEX IF NOT EXISTS idx_solicitations_state ON solicitations (state);
CREATE INDEX IF NOT EXISTS idx_solicitations_geom ON solicitations USING gist (geom);

CREATE TABLE IF NOT EXISTS solicitation_documents (
    id                  BIGSERIAL PRIMARY KEY,
    solicitation_id     BIGINT NOT NULL REFERENCES solicitations(id) ON DELETE CASCADE,
    name                TEXT,
    url                 TEXT NOT NULL,
    doc_type            TEXT NOT NULL DEFAULT 'attachment',
    bytes               BIGINT,
    storage_key         TEXT,
    text_extract        TEXT,
    fetched_at          TIMESTAMPTZ,
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (solicitation_id, url)
);
CREATE INDEX IF NOT EXISTS idx_soldocs_solicitation ON solicitation_documents (solicitation_id);
