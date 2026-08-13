-- Beta drag-to-detect view (2026-08): on-demand region scans, independent of
-- the takeoff line pipeline. Each row is one drag over one page: the scanned
-- rect, the resulting detected items, and provenance for the model call.
--   rect         [x0,y0,x1,y1] in pixels of the beta display render
--   display_dpi  DPI of that render (worker fills it; betaDisplayDpi(pageDims))
--   items        [{label, category, width_in, height_in, confidence, bbox}]
--                with bbox in the same display-render pixels
CREATE TABLE IF NOT EXISTS takeoff_detections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  takeoff_id uuid NOT NULL REFERENCES takeoffs(id) ON DELETE CASCADE,
  page integer NOT NULL,
  rect jsonb NOT NULL,
  display_dpi real,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','done','error')),
  items jsonb,
  crop_image_key text,
  model text,
  tokens_used bigint NOT NULL DEFAULT 0,
  error text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS takeoff_detections_takeoff_page_idx
  ON takeoff_detections (takeoff_id, page);
