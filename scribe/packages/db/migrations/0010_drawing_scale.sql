-- Drawing scale (Stage V item 0, v0-drawing-scale-plan.md §1): one scale
-- per located drawing region, in REAL inches per PDF point, with every
-- source that contributed (chain calibration, printed note, model-reported
-- note, manual calibration) and whether they agreed.
-- {"inPerPt": 0.6667, "confidence": 0.9, "agreed": true, "notToScale": false,
--  "unit": "in", "sources": [...]}
ALTER TABLE takeoff_detections ADD COLUMN IF NOT EXISTS scale jsonb;

-- Per-line geometry provenance (filled from PR C onward): the geometric size
-- from box x scale, which edges snapped, and where the final size came from.
ALTER TABLE takeoff_lines ADD COLUMN IF NOT EXISTS geom jsonb;
