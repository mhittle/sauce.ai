-- Invite-only sign-up (accounts-plan.md §1.8). The token is emailed once and
-- stored only as a sha256 hash; org_id NULL means sign-up creates a new org
-- (tenancy lands in 0014), a set org_id means "join this org".
CREATE TABLE IF NOT EXISTS invites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash text NOT NULL UNIQUE,
  email text NOT NULL,
  name text,
  org_name text,
  org_id uuid,
  credits_granted integer NOT NULL DEFAULT 0,
  invited_by uuid NOT NULL REFERENCES users(id),
  note text,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  used_by uuid REFERENCES users(id),
  revoked_at timestamptz,
  last_sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS invites_email_idx ON invites (lower(email));

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS phone text,
  ADD COLUMN IF NOT EXISTS terms_accepted_at timestamptz,
  ADD COLUMN IF NOT EXISTS terms_version text,
  ADD COLUMN IF NOT EXISTS terms_ip text,
  ADD COLUMN IF NOT EXISTS last_sign_in_at timestamptz;
