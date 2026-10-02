-- Usage ledger (accounts-plan.md §3.1, step 3a): every model call a takeoff
-- makes, costed at write time against a versioned rate. Instrument only — no
-- credits are charged from this.

-- Rates are list prices in integer cents per million tokens. Rows are never
-- updated: a price change is a new row with a later effective_from, and each
-- usage_events row pins the rate it was costed at.
CREATE TABLE IF NOT EXISTS model_rates (
  id serial PRIMARY KEY,
  model text NOT NULL,
  input_cents_per_mtok integer NOT NULL,
  output_cents_per_mtok integer NOT NULL,
  cache_write_cents_per_mtok integer NOT NULL,
  cache_read_cents_per_mtok integer NOT NULL,
  effective_from timestamptz NOT NULL DEFAULT now()
);

-- List prices 2026-10. OpenAI has no cache-write charge (write = input rate).
INSERT INTO model_rates (model, input_cents_per_mtok, output_cents_per_mtok, cache_write_cents_per_mtok, cache_read_cents_per_mtok, effective_from)
VALUES
  ('claude-sonnet-4-6', 300, 1500, 375, 30, '2026-01-01'),
  ('claude-haiku-4-5', 100, 500, 125, 10, '2026-01-01'),
  ('claude-opus-4-8', 500, 2500, 625, 50, '2026-01-01'),
  ('gpt-4.1', 200, 800, 200, 50, '2026-01-01');

CREATE TABLE IF NOT EXISTS usage_events (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES orgs(id),
  takeoff_id uuid REFERENCES takeoffs(id) ON DELETE SET NULL,
  stage text NOT NULL CHECK (stage IN ('classify','locate','detect','measure','spreadsheet','cross_validate','verify','extract')),
  model text NOT NULL,
  model_rate_id integer NOT NULL REFERENCES model_rates(id),
  input_tokens integer NOT NULL,
  output_tokens integer NOT NULL,
  cache_write_tokens integer NOT NULL DEFAULT 0,
  cache_read_tokens integer NOT NULL DEFAULT 0,
  image_count integer NOT NULL DEFAULT 0,
  -- The page the call is about, when it is about one page; page_kind is the
  -- drawing kind of that page or area ('plan' | 'elevation' | a page class).
  page_number integer,
  page_kind text,
  -- cents × 1e6: a 1k-token Haiku call is 0.1¢ and would round to 0 in cents.
  cost_microcents bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_events_takeoff_idx ON usage_events (takeoff_id);
CREATE INDEX IF NOT EXISTS usage_events_org_day_idx ON usage_events (org_id, created_at);
CREATE INDEX IF NOT EXISTS usage_events_created_idx ON usage_events (created_at);
