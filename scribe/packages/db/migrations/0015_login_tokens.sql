-- Email magic links (accounts-plan.md §1.4): a 15-minute single-use token
-- emailed to an existing user; stored hashed, like invites.
CREATE TABLE IF NOT EXISTS login_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash text NOT NULL UNIQUE,
  user_id uuid NOT NULL REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
