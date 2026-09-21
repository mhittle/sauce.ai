-- Onboarding tutorial (accounts-plan.md §2): a platform-chosen sample job is
-- cloned into each new org (same storage objects, so storage_id points at the
-- original's key space), and per-user coachmark progress lives on users.
ALTER TABLE takeoffs
  ADD COLUMN IF NOT EXISTS is_sample boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS storage_id uuid;
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS onboarding jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE org_settings
  ADD COLUMN IF NOT EXISTS sample_takeoff_id uuid REFERENCES takeoffs(id);
