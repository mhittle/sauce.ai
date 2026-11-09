-- External takeoffs (CabinetHub → Scribe → CabinetHub). A service caller may
-- tag an upload with where it came from and where to push the approved lines.
-- Additive: nullable columns, one new table, one org flag.

ALTER TABLE takeoffs
  ADD COLUMN IF NOT EXISTS external_source text,
  ADD COLUMN IF NOT EXISTS external_ref    text,
  ADD COLUMN IF NOT EXISTS callback_url    text;
CREATE INDEX IF NOT EXISTS takeoffs_external_idx
  ON takeoffs (external_source, external_ref) WHERE external_source IS NOT NULL;

-- One row per outbound delivery (one per approve). event_id is what the
-- receiver dedupes on; re-approving after a reopen is a new event.
CREATE TABLE IF NOT EXISTS takeoff_callbacks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  takeoff_id      uuid NOT NULL REFERENCES takeoffs(id) ON DELETE CASCADE,
  event           text NOT NULL,
  event_id        text NOT NULL UNIQUE,
  callback_url    text NOT NULL,
  payload         jsonb NOT NULL,
  attempts        integer NOT NULL DEFAULT 0,
  last_error      text,
  last_attempt_at timestamptz,
  delivered_at    timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS takeoff_callbacks_takeoff_idx
  ON takeoff_callbacks (takeoff_id, created_at);

-- The platform org (machine users: signal connector, CabinetHub connector) is
-- never blocked by credits; holds are still recorded for visibility.
ALTER TABLE orgs ADD COLUMN IF NOT EXISTS credits_exempt boolean NOT NULL DEFAULT false;
UPDATE orgs SET credits_exempt = true WHERE is_platform;
