-- Persisted quote tier (2026-08-13). The Quote Builder's tier picker
-- (Shaker base / Upgraded / Premium) was client-side only, so the STORED
-- subtotal/total (what the quotes list and DB show) came from the legacy
-- per-line engine while the builder displayed the validated tier estimate —
-- two different numbers for the same quote. The chosen tier is now stored and
-- the stored totals follow it.
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS pricing_tier text NOT NULL DEFAULT 'medium'
  CHECK (pricing_tier IN ('low','medium','high'));
