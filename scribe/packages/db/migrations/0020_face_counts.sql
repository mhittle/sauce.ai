-- Door and drawer-front counts per cabinet (SCR-015, owner 2026-10-21):
-- read from the drawing by the area scan (elevations only) or set by a
-- reviewer. NULL = not counted; faces then fall back to the tag heuristics.
ALTER TABLE takeoff_lines
  ADD COLUMN IF NOT EXISTS doors integer,
  ADD COLUMN IF NOT EXISTS drawers integer;
