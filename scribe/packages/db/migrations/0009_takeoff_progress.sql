-- Stage 1 UI (2026-09-11): live reading progress for the Reading screen.
-- Written by the worker at every stage boundary while status = processing:
-- { stage, done, total, message, started_at, updated_at }. Advisory only —
-- status stays the source of truth for the flow.
ALTER TABLE takeoffs ADD COLUMN IF NOT EXISTS progress jsonb;
