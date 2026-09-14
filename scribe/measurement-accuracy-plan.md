# Measurement accuracy plan — how should Scribe get the most accurate cabinet sizes?

**Status:** plan only (2026-09-15). Nothing here is built. Owner picks an
option (or none) before any code. Companion to `product-plan.md` §3V and
`v0-drawing-scale-plan.md`.

All numbers below come from the 18-quote staged kits
(`~/Desktop/Scribe Testing/staged-kits`, labels v3, zero-API replay through
`replay-staged.mjs`) plus the three MOLLY_CHARLEY_KITCHEN builds on prod
(2026-09-13). Two things could NOT be measured without fresh model calls and
are marked as such: per-area / per-cabinet measuring calls, and a reviewer
pass. Step 0 of the recommendation is the ~$4 experiment that gets them.

---

## 1. What the kits say

### 1.1 Where the F1 goes: counting, not sizing

| | 18 kits |
|---|---|
| Gold cabinets (labels v3) | 382 (21 per kit, 6–46) |
| Predicted by Find | 274 |
| Matched by the scorer | 158 → recall 41%, precision 58%, **F1 0.47** |
| Marked areas (auto-located regions in the kits) | 56 (3.1 per kit, max 6) |

Of the matched 158: width exactly right **62%**; width+height within 1"
**53%**; mean size error 1.53" when the answer said `measured: true`
(138 cabinets) vs 2.44" when it was estimated (20).

So if the count were perfect the set would score F1 1.0 by construction and
the remaining error is the size of roughly every second cabinet. Marking
granularity decides the count; measuring scope decides the size. They are
separate levers.

### 1.2 Fixing the count after Find costs about as much as marking by hand

By the scorer's alignment (which over-counts: a mis-sized cabinet shows up
as one miss plus one phantom):

| Kit kind | Kits | Gold / kit | Misses + phantoms / kit |
|---|---|---|---|
| Elevation sets (incl. 3 image kits) | 14 | 17.6 | ~15 |
| Plan-only sets | 4 | 33.8 | ~33 |

On elevation sets the human would touch about as many boxes fixing Find's
answer as drawing every cabinet themselves. The difference is what a touch
is: deleting/accepting a box Find already placed is one click; drawing a box
is a drag plus a category. On plan-only sets Find's run decomposition is the
problem (F1 0.21–0.44) and no marking scheme fixes it — a run box is what a
plan gives you.

### 1.3 The printed dimensions near a cabinet are not the missing information

`nearbyDims` (text-layer dimension strings within half a box of the cabinet)
was checked against the gold width of every matched cabinet:

| | matched cabinets |
|---|---|
| Any parsable printed dim near the box | 79 / 158 (50%) |
| Gold WIDTH among them | 41 (26%; 32% on elevation kits, 0% on plan kits and images) |
| Gold HEIGHT among them | 6 |
| Model width WRONG (60 cases) and the right width WAS listed nearby | **2** |

When the model already has the right number in its shortlist it uses it
(98 exact widths). When it is wrong, the right number is almost never in the
text layer next to the box — it is a drawn outline (q6/q8), a chain far from
the box, a schedule elsewhere, or an image. A deterministic "read the
printed dim" pass therefore has a ~26% ceiling; the gain has to come from
the model seeing the drawing legibly, or from the human.

Where dims ARE listed and the sizes are still off — q14 Charley (100% of
markers have dims, 3.4" error), q13 Boyle (71%, 3.0"), q24 Dean (5/5 widths
listed, heights wrong, 3.6"), q5 Wantoch (71%, 2.3") — the whole page is
what the model sees for elevations: a 24×36 sheet renders at ~37 DPI, where
`2'-4 1/4"` is a smudge. Plan areas already get a high-resolution crop
(measure-v6); elevation areas do not. That is the one untested lever with a
mechanism behind it.

### 1.4 Scale and geometry (already measured, 2026-09-14 (d))

Printed sizes beat box×scale on the labeled cabinets (0.64" vs 1.16" mean
error, printed closer 21×, geometry 5×). A trusted scale exists on 7 of 18
kits (text-layer chains or a printed note); images and outline-dimensioned
plans have none. Geometry stays a fallback and the draw-to-scale filler
(PR D), not a size source. Not re-proposed.

### 1.5 What the owner did on prod (correction UX evidence)

MOLLY_CHARLEY_KITCHEN, build 0a26eb66 (25 cabinets on 15 hand-marked
areas): 16 of 24 lines were touched at 19:13 UTC, all in the same minute,
confidence 1.0 — that is batch-accept, not size correction. 8 lines under
0.8 were left. The previous build 40f9cb79: 3 lines touched. No size was
typed on either. Either the sizes were right, or correcting them one field
at a time was not worth it — the kits say the second. Whatever ships must
make "this size is wrong" a one-click act on the review.

Also: 15 small hand-drawn areas produced 25 cabinets where the CRM quote
has 13 lines. Finer areas did not make the count better on this set.

---

## 2. Options

### Option A — areas + count gate + per-area measuring (recommended)

Marking stays whole areas (3 clicks per set). The Find step becomes the
count gate: each area's found boxes can be deleted (exists) and a missing
cabinet can be added by drawing a box INSIDE an area (new — today a drawn
box is always a new area). Build then measures ONE CALL PER AREA: the area
crop at full resolution with its markers painted (the plan-crop path,
extended to elevations) + that page + the set's schedule/plan pages as
context, answered under a strict JSON schema (structured outputs). The
review gains "Re-measure this cabinet" (tight crop + nearby dims, one call).

- **Clicks:** 3 areas + one click per Find error (~8 on a typical elevation
  set once the alignment double-count is discounted; more on plan sets).
- **Expected:** count F1 → whatever the human leaves; size error on
  elevation sets with legible dims should drop toward the 0.6–0.9" the
  legible kits already get (q3, q9, q21, q22). **Unmeasured** — Step 0.
- **Cost per set:** N area calls instead of one whole-set call; each ~15–25k
  input tokens (crop + page + context) → 3–6× today's measure spend on a
  4-page set, still under $1.
- **LOE 7** over four PRs (§3).

### Option B — mark every cabinet, no Find

The human draws one box per cabinet (category from the page kind, run boxes
on plans); measuring is per cabinet: tight crop + `nearbyDims` + the area
for context.

- **Clicks:** ~21 boxes per set (6–46), each a drag; on plan sets the human
  is drawing runs anyway, so the decomposition problem stays.
- **Expected:** count exact by construction on elevations; size no better
  than A's per-cabinet reading (the 26% text-layer ceiling applies to both).
- **Why not first:** it moves Find's work to the human on every set,
  including the ones Find gets right (q3 0.73, q9 0.78, q13 0.75). A's
  count gate lets the human do it only where Find failed, with the boxes
  already placed. B is A's PR 1 with Find turned off — keep it as a toggle
  if A's gate proves too slow to use.
- **LOE 5** (draw-a-cabinet mode in the wizard + per-cabinet measuring).

### Option C — today's pass + a reviewer pass + per-cabinet re-measure

Keep one whole-set call. Add the §3V V2 model reviewer (one call over the
annotated images + the line list → `confirm / doubt / wrong_size /
not_a_cabinet`) to flag sizes, and the per-cabinet re-measure on the
review for the human to act on a flag.

- **Clicks:** none up front; on the review, one per flag acted on.
- **Expected:** ceiling is the 47% of matched cabinets more than 1" off;
  the reviewer sees the same 37-DPI page the reader saw, so its catch rate
  on those is the open question. **Unmeasured** — Step 0 can run it on the
  same kits for ~$3 more.
- **Cost:** +1 call per set; needs the usage ledger (Stage 3a) to be
  visible per the product plan.
- **LOE 5**; lowest UX change, weakest mechanism.

### Correction UX (any option)

| Way to fix a wrong size | Build | Coverage | Notes |
|---|---|---|---|
| Type it (click-to-edit) | exists | 100% | Owner did not use it on prod; keep, make it the fallback |
| Re-measure this cabinet (tight crop + dims, one call) | LOE 2 | 100% | one click, replaces w/h/d, keeps the product pick unless dims change; cheapest to build that is not already built |
| Drag-to-scale on the review (PR D on A+B) | LOE 3 | 39% of kits have a trusted scale | draws the box's inches from the drawing scale; the right tool for a box the reviewer draws by hand, not for fixing a read |

Recommendation: ship re-measure-this-cabinet with whichever option; PR D
only when hand-drawn boxes on the review become common.

---

## 3. Recommendation, LOE and PR split (Option A)

**Step 0 — the $4 experiment (no product code, ~half a day).** Build the
per-area measure requests for the 18 kits from the existing kit PDFs (56
area crops at `fitDpi`, painted markers, page + context images, same
`measureUserText`), run them live through the harness's response slot
(`responses/measure.json` per kit, per area), replay through
`mergeMeasuredLines`, and compare against `summary.csv`: size error and
within-1" on matched, F1 per kit. Also run the reviewer pass (Option C)
on the same kits. **Ship gate:** per-area must not lose F1 on any kit and
must cut mean size error on the legible-dims elevation kits (q5, q13, q14,
q24). If it does not, Option A collapses to PR 1 + PR 3 and Option C's
reviewer is the next candidate.

| PR | Content | LOE | Depends on |
|---|---|---|---|
| 1 | Find step count gate: draw a box inside an area = one cabinet (category from the area kind), area chip shows "N found · 1 added", Build counts it. API: `POST /detections/:id/items {bbox, category, label?}` | 2 | — |
| 2 | Per-area measuring behind `MEASURE_SCOPE=area` (default stays `set` until Step 0 passes): the plan-crop path for every area kind, one call per area, structured outputs (`output_config.format`, needs the SDK bump from 0.70.1), per-area `response-{area}-{attempt}.txt`, progress "Measuring area 2 of 5". Harness: `prepare-staged.mjs --measure-scope area` | 3 | Step 0 |
| 3 | Review: "Re-measure this cabinet" (tight crop + `nearbyDims` + area crop, one call, `PATCH` w/h/d + note "re-measured"), keyboard `m` | 2 | — |
| 4 | (optional, after the usage ledger) V2 reviewer pass behind `VERIFY_LAYERS=1`, flags into the review's Flags panel | 3 | Step 0 |

Total LOE ≈ 7 (PRs 1–3), 10 with PR 4. PRs 1 and 3 are independent of the
experiment and are useful under every option; PR 2 is the one that needs
the number first.

**Decision needed from the owner:** Option A / B / C (or none), and a go
for Step 0's ~$4 of API on the kits.
