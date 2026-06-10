-- Scribe initial schema (PRD §5.5, §6.6). Applied by packages/db/src/migrate.ts,
-- tracked in _migrations. Keep this file append-only once deployed; later
-- changes go in new numbered files.

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  name text,
  role text NOT NULL DEFAULT 'estimator' CHECK (role IN ('estimator','sales','admin')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Prospector (PRD §5.5)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  type text NOT NULL,                -- socrata | samgov | agenda | ...
  base_url text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active',  -- active | paused | blocked | error
  last_cursor text,
  last_run_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_address text,
  jurisdiction text,
  permit_number text,
  parcel text,
  project_type text,
  valuation_cents bigint,
  est_cabinet_scope_usd numeric,
  description text,
  gc_name text,
  gc_contact jsonb,
  status text NOT NULL DEFAULT 'new'
    CHECK (status IN ('new','triaged','quoting','quoted','won','lost','ignored')),
  assigned_to uuid REFERENCES users(id),
  cabinet_relevance_score numeric,
  score_rationale text,
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS projects_status_score_idx
  ON projects (status, cabinet_relevance_score DESC);
CREATE INDEX IF NOT EXISTS projects_permit_idx ON projects (permit_number);
CREATE INDEX IF NOT EXISTS projects_address_idx ON projects (canonical_address);

CREATE TABLE IF NOT EXISTS project_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  s3_key text NOT NULL,
  doc_class text NOT NULL DEFAULT 'other',  -- plan_set | spec_book | other
  page_count integer,
  sha256 text,
  fetched_from_url text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS project_documents_sha_idx
  ON project_documents (project_id, sha256);

-- ---------------------------------------------------------------------------
-- Pricing (PRD §6.6)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS product_lines (
  id text PRIMARY KEY,
  name text NOT NULL,
  categories jsonb NOT NULL DEFAULT '[]'::jsonb,
  size_measure text NOT NULL CHECK (size_measure IN ('lf','sqft','unit')),
  material_rates jsonb NOT NULL DEFAULT '{}'::jsonb,
  finish_adders jsonb NOT NULL DEFAULT '{}'::jsonb,
  assembly_adder jsonb,
  dim_bounds jsonb NOT NULL DEFAULT '{}'::jsonb,
  lead_time_days integer NOT NULL DEFAULT 7,
  active boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Immutable versions; quotes pin the version they priced against.
CREATE TABLE IF NOT EXISTS pricing_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version integer NOT NULL UNIQUE,
  snapshot jsonb NOT NULL,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Takeoffs & quotes (PRD §6.6)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS takeoffs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid REFERENCES projects(id),
  uploaded_by uuid REFERENCES users(id),
  source_file_s3_key text NOT NULL,
  source_filename text,
  source_kind text NOT NULL CHECK (source_kind IN ('pdf','xlsx','csv','image')),
  status text NOT NULL DEFAULT 'processing'
    CHECK (status IN ('processing','extracted','review','approved','failed')),
  page_count integer,
  classified_pages jsonb,
  doc_confidence numeric,
  doc_summary jsonb,                -- uncertainties, unreadable pages, unit multipliers
  prompt_version text,
  tokens_used bigint NOT NULL DEFAULT 0,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS takeoff_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  takeoff_id uuid NOT NULL REFERENCES takeoffs(id) ON DELETE CASCADE,
  source_page integer,
  tag text,
  room text,
  qty numeric NOT NULL,
  category text NOT NULL,
  width_in numeric,
  height_in numeric,
  depth_in numeric,
  door_style text,
  material text,
  finish text,
  assembled boolean,
  notes text,
  confidence numeric NOT NULL,
  product_line_id text REFERENCES product_lines(id),
  resolved_params jsonb,
  match_confidence numeric,
  alternates jsonb,
  unmatched_reason text,
  reviewer_edited boolean NOT NULL DEFAULT false,
  raw_model_output jsonb,           -- audit: persist raw model output (PRD §6.3)
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS takeoff_lines_takeoff_idx ON takeoff_lines (takeoff_id);

-- Pre-correction extraction snapshots: every rep-corrected takeoff becomes a
-- labeled eval fixture (PRD §10).
CREATE TABLE IF NOT EXISTS eval_fixtures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  takeoff_id uuid NOT NULL REFERENCES takeoffs(id) ON DELETE CASCADE,
  extracted_lines jsonb NOT NULL,   -- pre-correction model output
  approved_lines jsonb,             -- post-review ground truth (set on approve)
  prompt_version text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company text NOT NULL,
  contact jsonb,
  bigcommerce_customer_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quotes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  takeoff_id uuid NOT NULL REFERENCES takeoffs(id),
  customer_id uuid REFERENCES customers(id),
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','sent','won','lost','expired')),
  pricing_config_id uuid NOT NULL REFERENCES pricing_configs(id),
  subtotal_cents bigint NOT NULL DEFAULT 0,
  markup_pct numeric NOT NULL DEFAULT 0,
  handling_cents bigint NOT NULL DEFAULT 0,
  freight_cents bigint NOT NULL DEFAULT 0,
  freight_pallets integer NOT NULL DEFAULT 0,
  freight_verified boolean NOT NULL DEFAULT false,
  actual_freight_cents bigint,      -- manual entry on won orders (PRD §6.5)
  total_cents bigint NOT NULL DEFAULT 0,
  valid_until date,                 -- created_at + 10 days price lock
  max_lead_time_days integer,
  line_prices jsonb,                -- per-line price breakdown at pricing time
  pdf_s3_key text,
  bigcommerce_draft_order_id text,
  sent_at timestamptz,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS quotes_status_idx ON quotes (status);

-- ---------------------------------------------------------------------------
-- Org settings & export templates
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS org_settings (
  id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  logo_s3_key text,
  quote_terms_md text NOT NULL DEFAULT '',
  quote_footer_md text NOT NULL DEFAULT '',
  default_handling_cents bigint NOT NULL DEFAULT 0,
  pallet_rate_cents bigint NOT NULL DEFAULT 70000,
  pallet_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  freight_provider text NOT NULL DEFAULT 'flat_pallet',
  updated_by uuid REFERENCES users(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS export_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  target text NOT NULL CHECK (target IN ('mozaik','kcd','generic')),
  delimiter text NOT NULL DEFAULT ',',
  unit_format text NOT NULL DEFAULT 'decimal_in' CHECK (unit_format IN ('decimal_in','mm')),
  columns jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Daily model-spend tracking for cost guardrails (PRD §9).
CREATE TABLE IF NOT EXISTS token_spend (
  day date NOT NULL,
  bucket text NOT NULL,             -- 'crawler' | 'takeoff'
  tokens bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (day, bucket)
);
