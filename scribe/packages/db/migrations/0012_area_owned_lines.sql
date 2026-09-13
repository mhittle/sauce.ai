-- Areas own their cabinets (Mark step PR 2, 2026-09-15): a correction
-- rescans and rebuilds ONE area instead of the whole takeoff.
ALTER TABLE takeoff_lines ADD COLUMN IF NOT EXISTS detection_id uuid;
CREATE INDEX IF NOT EXISTS takeoff_lines_detection_idx ON takeoff_lines (detection_id);
-- When an area's cabinets were last built into lines; NULL = new or changed
-- since the last build (the next build rebuilds exactly these).
ALTER TABLE takeoff_detections ADD COLUMN IF NOT EXISTS built_at timestamptz;
