-- Quotes get a human name (owner ask 2026-09-14): defaults to the job's
-- filename in the UI when null; editable on the quote screen.
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS name text;
