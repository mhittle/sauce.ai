-- Staged reads (2026-08-18): a detection now records WHICH KIND of drawing it
-- was located in. The measure stage needs it because a plan-view region boxes
-- a counter RUN (a plan draws no unit divisions) that has to be decomposed
-- into manufactured units, while an elevation region boxes one cabinet.
-- NULL = a wizard-drawn region, treated as an elevation (no decomposition).
ALTER TABLE takeoff_detections ADD COLUMN IF NOT EXISTS kind text;
