-- Beta detect wizard (2026-08): boxes are now DRAWN first (step 2) and only
-- sent to the model when the user runs detection (step 3), so detections gain
-- a pre-queue 'drawn' status as the new initial state.
ALTER TABLE takeoff_detections DROP CONSTRAINT IF EXISTS takeoff_detections_status_check;
ALTER TABLE takeoff_detections ADD CONSTRAINT takeoff_detections_status_check
  CHECK (status IN ('drawn','queued','running','done','error'));
ALTER TABLE takeoff_detections ALTER COLUMN status SET DEFAULT 'drawn';
