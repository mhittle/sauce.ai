-- Tenancy (accounts-plan.md §1.7): every user belongs to one org; takeoffs,
-- quotes, customers and eval fixtures are scoped by org. Existing rows all
-- move into the platform org (CabinetNow). Platform admins (today's
-- role = 'admin' users) operate across orgs; org_role is the in-org role.
-- org_settings stays the single platform-wide row (freight, pricing knobs,
-- quote terms) — per-org branding lands with the account screens.
CREATE TABLE IF NOT EXISTS orgs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  is_platform boolean NOT NULL DEFAULT false,
  logo_s3_key text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS orgs_platform_idx ON orgs (is_platform) WHERE is_platform;

INSERT INTO orgs (name, is_platform)
SELECT 'CabinetNow', true
WHERE NOT EXISTS (SELECT 1 FROM orgs WHERE is_platform);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS org_id uuid REFERENCES orgs(id),
  ADD COLUMN IF NOT EXISTS org_role text NOT NULL DEFAULT 'member',
  ADD COLUMN IF NOT EXISTS is_platform_admin boolean NOT NULL DEFAULT false;
UPDATE users SET org_id = (SELECT id FROM orgs WHERE is_platform) WHERE org_id IS NULL;
UPDATE users SET is_platform_admin = true, org_role = 'owner' WHERE role = 'admin' AND NOT is_platform_admin;
ALTER TABLE users ALTER COLUMN org_id SET NOT NULL;
DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT users_org_role_check CHECK (org_role IN ('owner','member'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE takeoffs      ADD COLUMN IF NOT EXISTS org_id uuid REFERENCES orgs(id);
ALTER TABLE quotes        ADD COLUMN IF NOT EXISTS org_id uuid REFERENCES orgs(id);
ALTER TABLE customers     ADD COLUMN IF NOT EXISTS org_id uuid REFERENCES orgs(id);
ALTER TABLE eval_fixtures ADD COLUMN IF NOT EXISTS org_id uuid REFERENCES orgs(id);
UPDATE takeoffs      SET org_id = (SELECT id FROM orgs WHERE is_platform) WHERE org_id IS NULL;
UPDATE quotes        SET org_id = (SELECT id FROM orgs WHERE is_platform) WHERE org_id IS NULL;
UPDATE customers     SET org_id = (SELECT id FROM orgs WHERE is_platform) WHERE org_id IS NULL;
UPDATE eval_fixtures SET org_id = (SELECT id FROM orgs WHERE is_platform) WHERE org_id IS NULL;
ALTER TABLE takeoffs      ALTER COLUMN org_id SET NOT NULL;
ALTER TABLE quotes        ALTER COLUMN org_id SET NOT NULL;
ALTER TABLE customers     ALTER COLUMN org_id SET NOT NULL;
ALTER TABLE eval_fixtures ALTER COLUMN org_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS takeoffs_org_idx      ON takeoffs (org_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS quotes_org_idx        ON quotes (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS customers_org_idx     ON customers (org_id);
CREATE INDEX IF NOT EXISTS eval_fixtures_org_idx ON eval_fixtures (org_id);

ALTER TABLE invites ADD CONSTRAINT invites_org_fk FOREIGN KEY (org_id) REFERENCES orgs(id);
