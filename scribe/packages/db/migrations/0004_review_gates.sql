-- Two-stage human review gates (2026-08: page picker + bounding-box review).
-- Status flow becomes: processing → awaiting_pages → processing →
-- awaiting_boxes → review → approved (+ failed). The dead 'extracted' status
-- stays in the CHECK — old rows may exist.

ALTER TABLE takeoffs DROP CONSTRAINT IF EXISTS takeoffs_status_check;
ALTER TABLE takeoffs ADD CONSTRAINT takeoffs_status_check
  CHECK (status IN ('processing','awaiting_pages','awaiting_boxes',
                    'extracted','review','approved','failed'));

-- User page selection from the picker gate: [{"page": n, "class": "floor_plan"?}]
-- (class present only when the user overrode the classifier's suggestion).
ALTER TABLE takeoffs ADD COLUMN IF NOT EXISTS selected_pages jsonb;

-- Bounding-box provenance per line (advisory-quality — visual anchors the
-- reviewer corrects, not ground truth):
--   bbox            [x0,y0,x1,y1] in pixels of the read image
--   read_image_key  storage key of the exact PNG the model read
--   read_rect       {"x0","y0","x1","y1"} in PDF points + {"dpi"} of that render
ALTER TABLE takeoff_lines ADD COLUMN IF NOT EXISTS bbox jsonb;
ALTER TABLE takeoff_lines ADD COLUMN IF NOT EXISTS read_image_key text;
ALTER TABLE takeoff_lines ADD COLUMN IF NOT EXISTS read_rect jsonb;
