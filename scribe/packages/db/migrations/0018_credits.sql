-- Credits (accounts-plan.md §3, step 3b). 1 credit = 1 page read at $1
-- (owner, 2026-10-02): no per-job minimum, each org's first job is free,
-- packs 25 / 100 / 500. Recorded and shown, never blocking, until
-- platform_settings.credits_enforced is turned on (after Stripe).

CREATE TABLE IF NOT EXISTS credit_ledger (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES orgs(id),
  -- pages: + signup_grant/admin_grant/purchase/release/refund, − hold;
  -- settle is 0 (the hold already took the pages; settle makes it final).
  delta integer NOT NULL,
  reason text NOT NULL CHECK (reason IN ('signup_grant','admin_grant','purchase','hold','settle','release','refund','adjust')),
  takeoff_id uuid REFERENCES takeoffs(id),
  hold_id bigint REFERENCES credit_ledger(id),
  balance_after integer NOT NULL,
  actor_user_id uuid REFERENCES users(id),
  external_ref text,
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS credit_ledger_org_idx ON credit_ledger (org_id, id DESC);
-- A hold is closed exactly once.
CREATE UNIQUE INDEX IF NOT EXISTS credit_ledger_hold_closed_idx
  ON credit_ledger (hold_id) WHERE reason IN ('settle', 'release');
-- One purchase row per Stripe checkout session (Task 3).
CREATE UNIQUE INDEX IF NOT EXISTS credit_ledger_purchase_ref_idx
  ON credit_ledger (external_ref) WHERE reason = 'purchase';

-- Cache of sum(delta); written only inside the ledger transaction.
ALTER TABLE orgs ADD COLUMN IF NOT EXISTS credit_balance integer NOT NULL DEFAULT 0;
ALTER TABLE takeoffs
  ADD COLUMN IF NOT EXISTS credit_hold_id bigint REFERENCES credit_ledger(id),
  ADD COLUMN IF NOT EXISTS pages_charged integer;

CREATE TABLE IF NOT EXISTS platform_settings (
  id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  min_pages_per_job integer NOT NULL DEFAULT 1,
  first_job_free boolean NOT NULL DEFAULT true,
  credits_enforced boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO platform_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Honour what invites already promised: "Pages included" on every invite
-- that created an org at sign-up becomes that org's signup grant.
WITH g AS (
  SELECT u.org_id, sum(i.credits_granted)::int AS pages, min(i.id::text) AS ref
  FROM invites i JOIN users u ON u.id = i.used_by
  WHERE i.used_at IS NOT NULL AND i.org_id IS NULL AND i.credits_granted > 0
  GROUP BY u.org_id
)
INSERT INTO credit_ledger (org_id, delta, reason, balance_after, external_ref, note)
SELECT org_id, pages, 'signup_grant', pages, ref, 'pages included on the invite (backfilled)'
FROM g;
UPDATE orgs SET credit_balance = l.total
FROM (SELECT org_id, sum(delta)::int AS total FROM credit_ledger GROUP BY org_id) l
WHERE l.org_id = orgs.id;
