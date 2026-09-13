# V0 — Drawing scale + geometry-first measuring: build plan

**Status:** A + B shipped (gated); **C measured and dropped 2026-09-14** — see
engineering-history 2026-09-14 (d): printed sizes beat geometry on the labeled
kits (0.64" vs 1.16"), F1 unchanged, the mismatch flag can't catch wrong
printed sizes. D (draw-to-scale on Review) remains possible on A + B.
**Decision (Rida, 2026-09-13):** scale is a property of the drawing, not the
cabinet. Establish it first, convert every box through it, return it in the
API so a newly drawn box has a set truth to measure against.

Written after reading `regions.ts`, `dim-skeleton.ts`, `pdf.ts`,
`detect.ts` (measure + merge), the measure/locate prompts, the DB schema and
the staged kit harness. Everything below names the real hook points.

---

## 0. What exists, what's missing

| Have | Where | Note |
|---|---|---|
| Printed dimension strings with positions, clustered into collinear chains | `@scribe/shared dim-skeleton.ts` (`extractDimSkeleton`, `dimsNearRect`, `parseDimInches`) | Positions are the text line's top-left in PDF points, upright-normalized. No width/height on `TextFragment` yet (the stext JSON has it). Grid rulers already filtered (`isGridRuler`). |
| Located drawing regions per page, with kind plan/elevation | `takeoff_detections.rect` (display px) + `display_dpi` + `kind`; `regions.ts` (`RectPt`, `mapBoxToPagePoints`, `padRectToPage`) | Region rect → PDF points is `rect × 72 / display_dpi`. |
| Per-line box in read-image pixels + the page rect and DPI of that image | `takeoff_lines.bbox`, `read_image_key`, `read_rect {x0,y0,x1,y1,dpi}` (`detect.ts` ~L649–886) | Box px → PDF pt: `pt = read_rect.x0 + px × 72 / dpi`. Renders and text share one upright normalization (`pdf.ts` rotation). |
| Measure pass returns sizes + `measured` flag + plan-run `units` | `MEASURE_SYSTEM` (measure-v6), `MeasuredCabinet` zod, `mergeMeasuredLines` (`detect.ts` L356+) | Sizes come from printed tags/dims, proportional guesses, or category defaults. **No scale, no geometry.** |
| Vector geometry access | mupdf 1.27: `new mupdf.Device({strokePath, fillPath})` + `Path.walk({moveTo, lineTo, …})`, driven by `page.run(device, ctm)` | Not used anywhere yet. `pdf.ts` only has `DrawDevice` for rasters. |
| Offline kit harness | `prepare-staged.mjs` (locate → detect → measure request files) / `replay-staged.mjs` (real merge + scoring vs labels v3), 18 kits in `~/Desktop/Scribe Testing/staged-kits/` | Zero-API replay. New deterministic steps slot in as saved `steps/*.json`. |
| Review drawing overlay with draw/move/resize in image-natural px | `BoxOverlay.tsx` (`onCreate(bbox)`), `SourceBoxPanel.tsx` (`NewLineForm`, inch fields empty) | Box edits are visual-only today. |

Missing: any stored real-world scale; any use of vector lines; geometry in
the measure decision; inches on a drawn box; a calibration fallback for
scans.

---

## 1. Data

**Migration `0010_drawing_scale.sql`.**

```sql
-- One scale per located drawing (a plan and an elevation on one sheet differ).
ALTER TABLE takeoff_detections ADD COLUMN IF NOT EXISTS scale jsonb;
-- {"in_per_pt": 0.6667, "confidence": 0.92, "agreed": true,
--  "sources": [{"kind":"note","in_per_pt":0.6667,"evidence":"SCALE: 1/4\" = 1'-0\""},
--              {"kind":"chain","in_per_pt":0.6612,"samples":7,"spread":0.03},
--              {"kind":"model","in_per_pt":0.6667,"evidence":"1/4\"=1'-0\""}],
--  "not_to_scale": false, "unit": "in"}

-- Per-line geometry provenance.
ALTER TABLE takeoff_lines ADD COLUMN IF NOT EXISTS geom jsonb;
-- {"width_in": 35.8, "height_in": 30.1, "depth_in": null,
--  "in_per_pt": 0.6667, "snapped": {"l":true,"r":true,"t":false,"b":true},
--  "size_source": "printed" | "geometry" | "default" | "manual",
--  "mismatch_in": 0.2}
```

Shared zod: `DrawingScale`, `LineGeom` in `packages/shared/src/scale.ts`.
`takeoffs` gets nothing new — the API assembles `scales` from detections.

---

## 2. Scale sources (PR A, zero API, LOE 2)

All pure functions in `@scribe/shared scale.ts`, unit-tested against the
18 kits' saved text layers.

**2.1 Title-block note.** Regex over page text fragments:
`SCALE[:\s]*` optional, then `(\d+(?:/\d+)?)"?\s*=\s*(\d+)'(?:-?(\d+)")?` (e.g.
`1/4" = 1'-0"`, `3/8"=1'`, `1 1/2" = 1'-0"`) and ratio forms `1:48`.
Yields paper-inch → real-inch ratio `R`; `in_per_pt = R / 72`. `N.T.S.` /
`NOT TO SCALE` → `not_to_scale: true` (geometry disabled for that drawing).
A note is attached to the region whose rect it sits under/inside (nearest
by vertical distance below the drawing, within the region's width); a
sheet-level note (title block) is the fallback for every region on the page.

**2.2 Dimension-chain calibration.** For each chain from
`extractDimSkeleton` whose tokens fall inside the region rect: consecutive
tokens `i, i+1` are at segment midpoints, so
`in_per_pt_sample = ((in_i + in_{i+1}) / 2) / |pos_{i+1} − pos_i|`. Use
token CENTERS — expose `w`/`h` on `TextFragment` (`pdf.ts`, stext line
bbox already has them; rotation-normalize like `x,y`). Median of samples;
accept when `samples ≥ 3` and interquartile spread `< 10%`. Chains that
are overall+subdivision pairs (`124"` above `6|27|24|24|27|6`) give a
second sample set: overall inches / span between the outer tokens.

**2.3 Model-reported scale.** Two prompt additions, both optional fields
so old kits still parse:
- `LOCATE_REGIONS_SYSTEM` (regions-v2): each region gets
  `"scale": "<printed scale note or null>"`.
- `MEASURE_SYSTEM` (measure-v7): top-level
  `"page_scales": [{"page": n, "scale": "<note>", "basis": "<what it read>"}]`.
Parsed with the 2.1 parser. A model value is a vote, never the only source
unless nothing else exists.

**2.4 Reconcile → one number per region.** Order: chain (measured on the
drawing itself) when accepted → note → model. `agreed` = every present
source within 8% of the chosen value; otherwise the region carries a
`scale_disagreement` flag with the values. `confidence`: chain 0.9,
note 0.8, model 0.6, manual 1.0; −0.2 when not agreed.

**2.5 Manual calibration (scans, photos).** `PUT
/takeoffs/:id/detections/:detectionId/scale {px_len, inches}` from the
review UI: `in_per_pt = inches / (px_len × 72 / dpi)`; kind `manual`,
overrides everything, recorded in `sources`.

Harness: `prepare-staged.mjs` writes `steps/scale.json` (per region, all
sources). No API cost.

---

## 3. Vector-snapped boxes (PR B, zero API, LOE 2)

**3.1 `pdf.ts: pageSegments(pageIndex, rect?)`.** Run the page through a
callback `mupdf.Device` whose `strokePath`/`fillPath` walk the path
(`moveTo`/`lineTo`; ignore `curveTo`), transform by `ctm`, keep segments
that are axis-aligned within 1.5°, length ≥ 4 pt, inside `rect` (padded
2%). Apply the same upright rotation as text/renders. Return
`{ h: [{y, x0, x1}], v: [{x, y0, y1}] }` sorted; cache per page. Skip
entirely for pages with no vector content (scans return `[]`).

**3.2 `snapBox(boxPt, segments, opts)`** (shared, pure). For each edge,
candidates = segments parallel to it, within tolerance
`max(6 pt, 3% of the box's perpendicular side)`, overlapping the box's
extent by ≥ 50%. Pick the nearest; move the edge only if a candidate
exists and the move is ≤ 15% of that side. Record which edges snapped.
Runs (plan kind) snap both ends along the run axis and the depth edge.
Never applied to raster-only pages.

Where: in `buildFromDetections` after markers are built and before the
measure call, so the annotated marker boxes the model sees are the snapped
ones too. Harness: `steps/segments-p{n}.json` + snapped boxes recorded
per marker.

---

## 4. Geometry-first measuring (PR C, LOE 2, one prompt bump)

**4.1 Before the call.** For each marker with a scaled region:
elevation → `geom.width_in = box_w_pt × in_per_pt`,
`geom.height_in = box_h_pt × in_per_pt`; plan → width and depth. Add to
the marker list text the model already receives (`measureUserText`):
`geometry from the drawing scale: ~35.8"w × 30.1"h (1/4" = 1'-0", chain-calibrated)`.
measure-v7 rule: "prefer a printed tag or dimension string; when none is
anchored to the cabinet, use the geometric size, not a default; report
`size_source`: printed | geometry | estimate".

**4.2 After the call — `mergeMeasuredLines(entries, cabinets, geom)`.**
Per marker, given model size `m`, geometric size `g`, tolerance
`tol = max(1.5", 6% of g)`:

| Case | Result |
|---|---|
| `measured` and `|m − g| ≤ tol` | printed `m`; `size_source: printed`; confidence +0.1 |
| `measured` and `|m − g| > tol` | printed `m` wins; **flag `size_mismatch`** ("printed 36", drawn 41.2""); confidence unchanged |
| not measured, scale confidence ≥ 0.75 | geometric `g`, width snapped to the nearest standard (3" steps, keep odd when a chain says so); `size_source: geometry`; NOT marked estimated |
| not measured, weak/no scale | today's behavior (defaults, `markEstimated`) |
| region `not_to_scale` | today's behavior; note on the line |

Depth on elevations stays the category standard unless a plan run of the
same room supplies it (room match is Stage V1's reconciliation; not here).
Plan runs: `run_length_in` cross-checked against geometric run length;
unit arithmetic uses whichever agrees with the chain.

**4.3 Harness A/B, the ship gate.** `replay-staged.mjs --geometry` replays
all 18 kits through the new merge with the saved measure responses
(prompt bump means the v7 prompt text is only measured on fresh reads —
the merge rules are measured now, the prompt later, ~$5 of API with owner
go-ahead). Ship when: elevation-kit F1 not down, plan-kind F1 up, mean
size error down, `size_mismatch` flags land on lines the labels say are
wrong more often than not. Prod flag `DRAWING_SCALE=1`, default off until
the A/B passes.

---

## 5. API + review UI (PR D, LOE 1.5)

- `GET /takeoffs/:id` adds `scales`: per read image `{read_image_key,
  page, in_per_px, confidence, agreed, not_to_scale, source}` (derived:
  `in_per_px = in_per_pt × 72 / read_rect.dpi`), and each line carries
  `geom`.
- `POST /takeoff-lines` with a `bbox` + `read_image_key` and no inches:
  the **server** fills width/height (or width/depth for plan images) from
  the scale, snapped to standard widths, `geom.size_source: geometry`.
  One implementation for UI and harness.
- `PATCH /takeoff-lines/:id`: an inch edit on a line with `geom` resizes
  `bbox` around its center (server-side); a bbox edit re-derives inches
  when `size_source` is geometry (never overwrites printed/manual).
- Review: `NewLineForm` opens prefilled from the scale ("from the drawing
  scale" hint); the sticky bar shows the image's scale ("1/4" = 1'-0" ·
  chain-calibrated") or "no scale — set one"; a **Set scale** tool in the
  source panel: drag a known length on the drawing, type inches → the
  manual endpoint. `size_mismatch` and `scale_disagreement` render in the
  Flagged filter with their evidence, which is the first real content of
  the Flags panel from PR 3.

---

## 6. Order, size, risks

| PR | Content | LOE | API cost |
|---|---|---|---|
| A | Scale sources + reconcile + migration + harness step + tests | 2 | 0 |
| B | Vector segments + snap + harness step + tests | 2 | 0 |
| C | Geometry in marker text, measure-v7, merge rules, flags, A/B | 2 | ~$5 once |
| D | API scales, draw-to-scale, calibration tool, flags in Review | 1.5 | 0 |

Total ≈ 7.5 (the plan said 6; the calibration tool and the server-side
inch derivation are the extra). A and B are independent and can run in
parallel; C needs both; D needs C's data shapes.

**Risks and how each is bounded.**
- *Snapping to the wrong line on busy sheets* — visible in the harness as
  size error; printed dims still override a bad snap; edge moves capped at
  15%.
- *Multiple scales per sheet / details at 1" = 1'* — per-region scale +
  note-to-region attachment; a region with a chain calibration ignores the
  sheet note.
- *Text positions are top-left, not centers* — fixed by exposing `w,h`
  (2.2); until then chain samples skew by half a token width.
- *Metric drawings* — `parseDimInches` is inches-only; mm tokens fail to
  parse, so no chain calibration and `unit: "mm"` is not attempted in V0.
  Note-only scale still works. Flag when ≥ 3 fragments look like `\d{3,4}`
  with no inch marks.
- *Scans* — no text, no vectors: model-reported note + manual calibration
  only. Geometry stays off until a manual scale is set.
- *`N.T.S.` drawings* — detected, geometry disabled, line note.

**Acceptance.** On the 18 kits: plan-kind F1 above 0.32, elevation F1 not
below 0.55, mean size error down from 1.7"; a drawn box on a calibrated
drawing prefills within one standard width of the printed size on the 5
labeled elevation kits; a scan with a manual scale prefills correctly.
