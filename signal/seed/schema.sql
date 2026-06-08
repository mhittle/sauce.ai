-- sauce.ai/signal — canonical schema (PostgreSQL 15+ / PostGIS / pgvector)
--
-- This is the full, idempotent schema. Apply to a fresh database to bring it
-- to the current shape; incremental changes go in seed/migrations/ and are
-- folded back here. See signal/INSTALL.md.
--
-- Design notes:
--   * Signals are stored EAV-style (project_signals -> signal_catalog) so a
--     new signal is a registry row, NOT a schema change (PRD §8 design req).
--   * Every permit keeps its raw_payload jsonb for provenance (PRD §16).
--   * Geometry uses SRID 4326; spatial work goes through PostGIS.
--   * Embeddings use pgvector for the semantic scope filter (PRD §9).

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- Jurisdictions: a city/county + which adapter serves it + freshness state.
-- field_map maps canonical column -> source column name for this dataset.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jurisdictions (
    id                  BIGSERIAL PRIMARY KEY,
    slug                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    state               TEXT,
    county              TEXT,
    source_type         TEXT NOT NULL DEFAULT 'socrata',   -- socrata|arcgis|accela|etrakit|cityview|paid
    platform_domain     TEXT,                              -- e.g. data.cityofchicago.org
    dataset_id          TEXT,                              -- e.g. ydr8-5enu
    field_map           JSONB NOT NULL DEFAULT '{}'::jsonb,
    adapter_config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    last_good_pull      TIMESTAMPTZ,
    known_lag_days      INTEGER,                           -- documented portal lag
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Projects: the deduplicated real-world job (may aggregate many permits).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id                  BIGSERIAL PRIMARY KEY,
    jurisdiction_id     BIGINT REFERENCES jurisdictions(id),
    primary_address     TEXT,
    geom                geometry(Point, 4326),
    parcel_apn          TEXT,
    category            TEXT,                              -- derived: hospitality|office|...
    value_tier          TEXT,                              -- derived bucket
    lead_score          NUMERIC(8,3) NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'new',       -- new|called|qualified|ignored
    dedup_confidence    NUMERIC(4,3),
    scope_summary       TEXT,                              -- LLM one-line summary (cached)
    scope_embedding     vector(1536),                      -- pgvector semantic filter
    llm_classified_at   TIMESTAMPTZ,
    crm_id              TEXT,                              -- set after CRM push, prevents dupes
    notes               TEXT,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_projects_geom ON projects USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_projects_lead_score ON projects (lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status);
CREATE INDEX IF NOT EXISTS idx_projects_apn ON projects (parcel_apn);

-- ---------------------------------------------------------------------------
-- Permits: raw normalized records, each linked to a project.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permits (
    id                  BIGSERIAL PRIMARY KEY,
    jurisdiction_id     BIGINT NOT NULL REFERENCES jurisdictions(id),
    project_id          BIGINT REFERENCES projects(id),
    permit_id           TEXT NOT NULL,                     -- source permit number
    source_type         TEXT NOT NULL DEFAULT 'socrata',
    source_url          TEXT,
    permit_type         TEXT,
    permit_subtype      TEXT,
    work_description    TEXT,
    valuation           NUMERIC(14,2),
    status              TEXT,
    application_date    DATE,
    issue_date          DATE,
    expiration_date     DATE,
    last_status_change  DATE,
    final_date          DATE,
    address             TEXT,
    geom                geometry(Point, 4326),
    parcel_apn          TEXT,
    owner_name          TEXT,
    applicant           TEXT,
    contractor_name     TEXT,
    contractor_license  TEXT,
    use_type            TEXT,
    occupancy           TEXT,
    sqft                NUMERIC(12,1),
    units               INTEGER,
    fees                NUMERIC(12,2),
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (jurisdiction_id, permit_id)
);
CREATE INDEX IF NOT EXISTS idx_permits_project ON permits (project_id);
CREATE INDEX IF NOT EXISTS idx_permits_geom ON permits USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_permits_status ON permits (status);
CREATE INDEX IF NOT EXISTS idx_permits_issue_date ON permits (issue_date);
CREATE INDEX IF NOT EXISTS idx_permits_raw ON permits USING gin (raw_payload);
CREATE INDEX IF NOT EXISTS idx_permits_desc_trgm ON permits USING gin (work_description gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- Inspections: fuels distress signals where available.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inspections (
    id                  BIGSERIAL PRIMARY KEY,
    permit_id           BIGINT NOT NULL REFERENCES permits(id),
    inspection_type     TEXT,
    inspection_date     DATE,
    result              TEXT,                              -- pass|fail|reinspect
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_inspections_permit ON inspections (permit_id);

-- ---------------------------------------------------------------------------
-- Contractors / contacts: cross-referenced against our ~2,000 known contacts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contractors (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    normalized_name     TEXT NOT NULL,
    license             TEXT,
    in_crm              BOOLEAN NOT NULL DEFAULT FALSE,    -- known-GC flag
    crm_company_id      TEXT,
    active_project_count INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (normalized_name, license)
);
CREATE INDEX IF NOT EXISTS idx_contractors_norm ON contractors (normalized_name);

CREATE TABLE IF NOT EXISTS contacts (
    id                  BIGSERIAL PRIMARY KEY,
    contractor_id       BIGINT REFERENCES contractors(id),
    name                TEXT,
    email               TEXT,
    phone               TEXT,
    role                TEXT
);

-- ---------------------------------------------------------------------------
-- Signal registry + per-project signal values (EAV; new signal = new row).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_catalog (
    id                  TEXT PRIMARY KEY,                  -- e.g. distress_stalled
    label               TEXT NOT NULL,
    tier                TEXT NOT NULL,                     -- ingested|derived|enrichment
    datatype            TEXT NOT NULL,                     -- bool|number|category|text|geo
    how_derived         TEXT,
    is_facet            BOOLEAN NOT NULL DEFAULT TRUE,     -- exposes as filter facet
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_signals (
    project_id          BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    signal_id           TEXT NOT NULL REFERENCES signal_catalog(id),
    value_bool          BOOLEAN,
    value_num           NUMERIC,
    value_text          TEXT,
    value_json          JSONB,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, signal_id)
);
CREATE INDEX IF NOT EXISTS idx_project_signals_signal ON project_signals (signal_id);

-- ---------------------------------------------------------------------------
-- Triage: saved searches + scored rules + digests.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    is_admin            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    owner_user_id       BIGINT REFERENCES users(id),
    filters             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rules (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    owner_user_id       BIGINT REFERENCES users(id),
    profile             TEXT NOT NULL DEFAULT 'default',
    weights             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {signal_id: weight}
    threshold           NUMERIC(8,3) NOT NULL DEFAULT 0,
    filters             JSONB NOT NULL DEFAULT '{}'::jsonb,
    digest_recipients   JSONB NOT NULL DEFAULT '[]'::jsonb,
    send_time           TEXT,                                  -- HH:MM local
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS digests (
    id                  BIGSERIAL PRIMARY KEY,
    rule_id             BIGINT REFERENCES rules(id),
    run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    project_ids         JSONB NOT NULL DEFAULT '[]'::jsonb,
    sent_to             JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- ---------------------------------------------------------------------------
-- Observability: one row per source pull.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_runs (
    id                  BIGSERIAL PRIMARY KEY,
    jurisdiction_id     BIGINT REFERENCES jurisdictions(id),
    source_type         TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running',       -- running|ok|error
    permits_fetched     INTEGER NOT NULL DEFAULT 0,
    permits_upserted    INTEGER NOT NULL DEFAULT 0,
    projects_touched    INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_juris ON ingest_runs (jurisdiction_id, started_at DESC);
