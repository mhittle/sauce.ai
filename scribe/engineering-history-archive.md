# sauce.ai/scribe — engineering history archive

Full verbatim text of entries condensed out of `engineering-history.md`.
Newest-first within each date. Consulted on demand (grep by date / PR# / topic);
not read during onboarding.

---

## 2026-09-14 (b) — one flow: the wizard is the pipeline

**Owner:** "make the beta flow the default, I don't want 2 modes." Until now
PDFs had two paths: the automatic staged read (locate → detect → measure →
price, no human between pages and review) and the wizard (draw → detect →
build) as an advanced hand-off. Now there is one: after the page pick the
worker locates the drawings, seeds them as `drawn` boxes, renders the
wizard's page images, and parks at **`awaiting_boxes`**; the wizard opens on
Mark with the regions pre-boxed; the human adjusts, Finds, Builds; the build
lands on review. Status flow: `processing → awaiting_pages → processing →
awaiting_boxes → processing → review → approved`.

**Shipped.**
- `staged.ts` — stages 3–4 (auto detect + build) removed; seeding writes
  `status: "drawn"`, pre-renders `beta/pages/{n}.png` for every seeded page,
  stores the seeding warnings in `docSummary {warnings, seeded: true}`, sets
  `awaiting_boxes`, final progress "Drawings found — mark the cabinet areas".
- `detect.ts buildFromDetections` prepends the seeded warnings to the built
  summary (no-scale / disagreement / skipped-page notes survive the build).
  `index.ts` beta_build now passes `evalFixture: true` — every build
  snapshots pre-correction lines for the eval corpus, as the auto path did.
- API `build-takeoff` accepts `awaiting_boxes`.
- Web: `BetaDetect` rewritten as the three-step wizard (Mark · Find · Build)
  — pages come from `takeoff.selectedPages`, Reading screen while
  `processing`, no page step, no "beta" badge; `PagePicker` submits into
  the wizard and the "draw the regions yourself" disclosure is gone;
  `TakeoffReview` forwards `awaiting_boxes` to the wizard; `BoxReview.tsx`
  (the 2026-08-10 legacy box gate) deleted; Jobs rows link `awaiting_boxes`
  to the wizard; label "Mark cabinets".

**Also (owner ask, same day): quotes have a name.** Migration `0011`
`quotes.name`; `POST /quotes {name?}` and `PATCH /quotes/:id {name}`;
`GET /jobs` carries `quote.name`. Review's "Looks right → Quote" opens a
"Name this quote" dialog prefilled with the filename minus extension; the
Quote screen's title is the name, renamed in place (click → type → Enter);
the Quotes list shows the name with the filename beside it. Null name falls
back to the job's filename everywhere, so old quotes need nothing.

**Why the owner saw the old UI:** their checkout at
`/Users/rd/Documents/Homize/sauce.ai` was on `scribe/estimate-reading-accuracy`
(June, 105 commits behind) and the deployed/local build had PR 1 only —
PRs 2–4 reached `main` via #260 on 2026-09-13. Pull `main`, rebuild.

**Not changed.** `STAGED_READS=0` still selects the classic one-shot reader
(emergency knob, not a mode); the harness still replays locate → detect →
measure end to end; images and spreadsheets keep their gate-less paths.

**Gotchas.** (1) A build failure restores `awaiting_boxes` (prior status),
so the user lands back in the wizard with their boxes. (2) The wizard's
Build step confirms only when the takeoff already has lines (re-marking a
reviewed takeoff); a first build just builds. (3) `docSummary.seeded` is
how the build knows which warnings to carry — don't drop the flag.

---

## 2026-09-14 (c) — Mark step: marked areas are unmistakable; overlap guard

**Owner:** in Mark they double-marked a drawing because the existing region
was a faint dashed outline, then saw the cabinets twice after Find.

- `BoxOverlay` `underlays` → `areas: OverlayArea[]` — each marked area is a
  solid redline rectangle with a tinted fill, a label chip ("Area 2 · 3
  found" / "not scanned" / "scanning…" / "failed") and its own × button
  (`onAreaRemove`), highlighted on hover (`onAreaHover`).
- Wizard: chip list of the page's areas under the drawing (hover highlights
  the box, × removes); areas numbered per page in creation order.
- **Overlap guard:** a new box whose intersection covers ≥50% of the smaller
  of it and an existing area is refused with a toast naming the area and
  flashing it — the same cabinets must not be scanned twice. Partial overlaps
  under 50% (padding) still draw.

Verified on the mock (chips + SVG labels present, console clean); web
build green. The guard's geometry is `overlapFraction` in `BetaDetect.tsx`.

---

---

## 2026-09-14 (d) — V0 PR C measured and DROPPED: printed sizes beat geometry

**Owner:** "test a bit, if it is better continue" → it was not; "forget it".
Code discarded (never committed). The evidence, so nobody re-runs this blind:

- **Free A/B on the 18 kits** (saved measure responses replayed through a
  geometry-first merge: box×scale as baseline, printed dims override when they
  agree, geometry replaces defaults when nothing is printed): **F1 0.465 →
  0.465 on every kit; size error 1.64" → 1.66"**. Two reasons: (1) the
  measure-v6 responses mark almost every cabinet `measured: true`, so
  "printed wins" leaves geometry nothing to do (q21 33/33, q22 22/22, q9
  26/26); (2) on plan-only kits the geometry sits on the RUN while the lines
  are the model's UNITS, so it never touches them.
- **Printed vs geometry against the labels** (66 matched cabinets, 7 kits
  with a trusted scale): mean |printed − gold| **0.64"** vs |geometry − gold|
  **1.16"**; printed closer 21×, geometry closer 5×, tie 40. Geometry is a
  decent fallback (inside one standard width), not a better answer. (Caveat:
  the matching used printed widths, so this is biased toward printed.)
- **The size-mismatch flag cannot catch what it was meant to.** Of 48
  confirmed-correct printed sizes, 12 sit >1.5" from their box (false
  alarms at the planned tolerance); of the 18 WRONG printed sizes, the
  median distance to the box is 0.41" — when the model mis-sizes a cabinet
  its box is usually wrong the same way. At max(3", 12%): 3 false alarms,
  3 of 18 caught.

**What survives of V0.** PR A (scale sources) and PR B (vector snap) are on
main, gated off, harmless. Geometry-from-scale remains the right tool for
the ORIGINAL ask — a box the reviewer draws gets its inches (~1.2" accuracy)
instead of empty fields — that is PR D, if wanted, and needs only PR A/B.
Whether telling the model the geometric size improves its own answers is
untested (needs fresh reads, ~$5). Not pursued.

---

---

## 2026-09-15 — Mark step PR 1: side panel, no pre-selection, kind + scale on the area

**Owner (approved plan):** (1) the cabinet table beside the drawing, not
under it; (2) no pre-selected areas — the whole-page fallback boxed an
entire letter-size sheet as "Area 1"; (3) selection synced both ways
between drawing and table. PR 2 (areas own their cabinets; a correction
rescans one area) follows.

**Shipped.**
- `staged.ts` — the extract stage no longer locates or seeds anything: it
  renders the wizard's page images for the selected pages (progress
  "Rendering page N for marking"), stores the estimation/schedule notes in
  `docSummary {warnings, seeded: true}`, parks at `awaiting_boxes`. One
  fewer vision call per page in prod. The harness (`prepare-staged.mjs`)
  still runs locate as the stand-in for the human's boxes.
- Area **kind** (plan | elevation): `POST /detections` derives it from the
  page type chosen at Pages (`selectedPages[].class`, else the classifier's
  call) — `areaKindForPage`; optional `kind` in the body; new
  `PATCH /takeoffs/:id/detections/:id {kind}` (clears found cabinets, back
  to `drawn`). The chip in the wizard has a plan/elevation select.
- Area **scale** (PR A) now computed in `detectRegion` at scan time from
  the page's dimension strings inside the rect + the printed note, stored
  on the detection as before.
- Wizard layout: `[9rem rail][drawing][22rem panel]`; the panel holds the
  Areas list (kind select, ×, "Clear page" with confirm) and the cabinets
  table, and scrolls on its own. Two-way selection: clicking a dot scrolls
  its row into view (`data-box-id` + `scrollIntoView`); clicking a row
  selects and scrolls the drawing (BoxOverlay already did that).

**Gotchas.** (1) Old takeoffs parked at `awaiting_boxes` with seeded
`queued`/`drawn` regions still work — the wizard shows whatever
detections exist. (2) `DrawingScale` on a detection is now written by the
scan, so an area edited after scanning keeps the old scale until rescanned
(PR 2 resets status on edit). (3) `locateRegions`/`locateRooms` are
unused in prod now; kept for the harness.

---

---

## 2026-09-15 (b) — Mark step PR 2: areas own their cabinets; corrections rebuild one area

**Owner-approved decisions (2026-09-15):** removing an area deletes its
cabinets; resizing/moving (or changing plan↔elevation) discards its
cabinets until rescanned; an approved takeoff must be reopened before
amending; kind comes from the page type with a per-area override.

**Shipped.**
- Migration `0012`: `takeoff_lines.detection_id` (+ index) — the area a
  cabinet came from; `takeoff_detections.built_at` — when the area's
  cabinets were last built (NULL = new or changed → the next build takes
  exactly these). `CabinetLineItem.detection_id`; `ReadLine.detection_id`.
- `buildFromDetections` is now **scoped**: it measures only `done` areas
  with `built_at IS NULL`, `replaceLinesForDetections` deletes those areas'
  previous lines (+ derived faces) and inserts the new ones, stamps
  `built_at`, and `priceAndExpand(takeoffId, log, {lineIds})` matches and
  expands ONLY the inserted lines — manual product picks, edited inches and
  accepted confidence on untouched areas survive. Eval fixture = every
  area-built cabinet. Error when nothing is unbuilt.
- API: `build-takeoff` needs unbuilt scanned areas (409 on approved);
  `PATCH /detections/:id {kind?, rect?}` resets the area (drawn, items
  null, built_at null) and deletes its lines (`removed_lines` in the
  response); `DELETE /detections/:id` deletes its lines too;
  `POST /takeoffs/:id/reopen` (approved → review; transition added to
  `TAKEOFF_STATUS_TRANSITIONS`).
- Web: areas are **movable** (drag the label chip) and **resizable**
  (corner handles) in `BoxOverlay` (`onAreaChange`), reusing the box
  drag machinery; the interior stays pass-through for drawing. The wizard
  PATCHes the rect, confirms when the area is already in the takeoff, and
  tells you how many cabinets were removed. Build button: "Update N areas
  (M cabinets)" on a reviewed takeoff, disabled with a hint when nothing
  is unbuilt; area notes say "in takeoff". Approved takeoffs lock the
  wizard with a banner; Review's More menu gains "Reopen for changes" and
  "Add or change areas…" (review only).

**Gotchas.** (1) Lines drawn by hand on the review screen have
`detection_id NULL` and are never touched by area builds. (2) Legacy
takeoffs built before 0012 have lines with NULL `detection_id` and areas
with NULL `built_at` — a "rebuild" there would ADD a second copy of every
cabinet; the wizard shows those areas as unbuilt. To re-do a legacy
takeoff, clear its areas (which deletes nothing, since nothing links) and
delete the old lines by hand, or start a new job. (3) `priceAndExpand`
without `lineIds` keeps the old full-pass behaviour (classic path).

---

---

## 2026-09-15 (e) — session wrap-up: measuring still fails in prod after #272; next session = evidence first

**Context.** Session 2026-09-10→15 shipped the product pivot (Stage 1 UI
#254–#260), one flow (#265), V0 scale A+B (#262/#264, gated; C dropped), the
Mark-step rework (#266/#268), and three prod fixes on the owner's live job
MOLLY_CHARLEY_KITCHEN: ANY-list build failure (#270), wizard not forwarding
to the review (#271), measuring answer unparseable → all sizes defaulted
(#272). All merged to `main` and deploy-verified (bundle hash + unique
string; API `/health/db` 200).

**Open (owner report after #272 deployed, NOT diagnosed — logged SCR-013):**
Build and "Measure again…" STILL error on the measuring step and the owner
lands back on the wizard, not the review. No logs, wizard error text, or the
persisted `beta/measure/response-{0,1}.txt` were pulled this session — the
next session must start from that evidence, not from code reading. A failed
build goes `processing → awaiting_boxes` (wizard, error shown, Build
clickable) BY DESIGN, so "not taken to the review" may be the error, not a
routing bug; confirm before touching routing (`BetaDetect.tsx` ~156/275).

**Next session also owes a plan (not code) on measurement accuracy:** marking
granularity (areas vs individual cabinets vs runs), measuring scope (one call
over all pages vs per area vs per cabinet crop + `nearbyDims`), a check pass
(product-plan §3V), what to do with printed dims / drawing scale (A+B) / a
schedule when present, and the cheapest correction UX when a size is wrong.
Options must carry kit numbers (`replay-staged.mjs`, 18 kits, F1 0.47
baseline). Geometry-as-size-override was measured and dropped — don't
re-propose it (2026-09-14 (d)).

**Housekeeping this entry:** archived 2026-08-05 → 2026-09-13 (b) verbatim
(file was 65 KB vs the 34 KB budget); condensed summaries below. Nothing new
in Load-bearing state — every prod change this session is in the repo
(migrations 0009–0012 apply at API boot).

---

## 2026-09-14 — V0 PR B: vector segments + box snapping (gated, measured on the kits)

**Shipped (zero API).**
- `pdf.ts: pageSegments(pageIndex, {rect?, minLenPt?})` — runs the page
  through a callback `mupdf.Device` (`strokePath` + `fillPath`, so CAD
  exports that draw lines as thin filled rectangles count), walks each
  path (`moveTo`/`lineTo`/`closePath`; curves skipped), transforms by the
  op's ctm, keeps segments axis-aligned within ~1.5°, ≥4 pt, normalizes
  upright with the same rotation as the text layer, merges collinear
  pieces (`mergeSegments`). Cached per page. Raster pages → `{h:[],v:[]}`.
  **Convention pinned by test:** mupdf's device space for a page is the
  same top-left-origin point space as the stext bboxes (a PDF rect at
  y=100..250 on a 792 pt page lands at 542..692).
- `@scribe/shared snap.ts`: `snapBox(box, segments, opts)` — per edge, the
  nearest parallel segment within `max(6 pt, 10% of the perpendicular
  side)` that overlaps ≥50% of the side wins (longer overlap breaks ties);
  an edge never moves more than 15% of its side; reports which edges
  snapped and the largest relative move. `LineGeom` zod
  (`takeoff_lines.geom`; PR B fills `snapped` + `snap_moved`).
  `CabinetLineItem.geom` (optional) carries it through the merge.
- `detect.ts buildFromDetections`: behind **`DRAWING_SCALE=1`**, every
  detector box is snapped in display px BEFORE the annotated marker images,
  plan crops and persisted bboxes derive from it (`snapDisplayBox`);
  `MarkerEntry.geom` → line `geom`. `replaceLines` persists it.
- Harness: `DRAWING_SCALE=1 prepare-staged.mjs` writes `steps/snap.json`
  (segment counts per page, before/after per box, edges, move).

**Design change from the plan:** search window 10% of the side, not 3% —
the July spike's "loose boxes" are looser than 3%, and the 15% move cap
plus the overlap rule already bound the risk.

**Measured on the 18 kits (zero API):** 246 detector boxes, 204 touched
(83%), 144 snapped on all four edges; mean move of a touched box 4.3%,
median 4.0%. Image kits (q2, q10, q11) untouched, as designed. Plan-only
sets whose dimensions are drawn outlines (q1, q6, q8) still carry
thousands of vector segments, so snapping works there even though text-
layer calibration (PR A) did not. q24 has segments but no box within the
window — worth a look in PR C's A/B. Nothing consumes the snapped boxes
for SIZE yet (PR C); with the flag off prod is unchanged.

**Gotchas.** (1) `page.run(device, Matrix.identity)` — the ctm the
callbacks receive already includes the page's base transform; do not
pre-multiply. (2) `mupdf.PDFDocument.addPage()` returns an unattached page
object — tests must `insertPage(-1, obj)` or `loadPage(0)` throws "invalid
page number: 1". (3) Wizard-drawn detections (kind null) snap too; a
human-drawn box on a raster page is untouched.

---

## 2026-09-13 (c) — V0 PR A: drawing-scale sources, measured on the 18 kits

**Context.** Stage V item 0 (`v0-drawing-scale-plan.md`): scale is a property
of the drawing. PR A lands the sources and storage with zero API cost; B–D
follow. Also found and fixed the stacked-PR merge problem (see load-bearing
state): PRs 2–4 were not on `main`; #260 lands them.

**Shipped.**
- `@scribe/shared scale.ts` (37 tests): `parseScaleNote` (architect's
  `1/4" = 1'-0"` incl. mixed numbers and curly quotes, `1:48`, `N.T.S.`),
  `findScaleNotes`, `attachNotesToRegions` (a note belongs to the drawing it
  sits under, sheet note as fallback), `chainCalibration`, `reconcileScale`
  (manual > accepted chain > note > model; 8% agreement; −0.2 confidence on
  disagreement; NTS beats all but manual), `scaleForRegion` (one call per
  region), `inPerPx`. `DrawingScale`/`ScaleSource` zod.
- `TextFragment` gains optional `w,h` (mupdf stext line box, rotation-
  normalized); `extractDimSkeleton` now centres tokens when widths are
  present — chain calibration measures centre-to-centre distances.
- Migration `0010`: `takeoff_detections.scale`, `takeoff_lines.geom` (geom
  is filled from PR C). `staged.ts` computes `scaleForRegion` for every
  seeded region (page text + the model's note) and stores it, warning when
  no scale is found or sources disagree. regions-v2 prompt asks for the
  printed scale note per region (`PageRegion.scale`, tolerant parse).
- `PUT /takeoffs/:id/detections/:detectionId/scale {px_len, inches}` —
  manual calibration, overrides and is kept in the source list.
- Harness: `prepare-staged.mjs` writes `steps/scale.json` per region.

**Measured on the 18 kits (zero API), which changed the design.** First
pass used the median of all adjacent-token samples with an IQR spread
gate: only 2 regions accepted, spreads of 0.5–4.6. Diagnosis on q7/q21:
the true scale is always a TIGHT CLUSTER of samples, contaminated by reveal
labels (1 1/2", 2"), cabinet numbers ("1", "3") that parse as inches, and
chains that jump across neighbouring drawings at the same y. Rule now:
skip pairs with a token under 3" or a gap under 8 pt, then take the
DENSEST ±10% cluster; accept at ≥3 members. Result: chain calibrations
that agree with the printed note on every sheet that has one (q3, q7, q22,
q23 at 1/2" and 1/4"), and accepted chains on note-less sheets (q21).
Text-layer coverage is the ceiling: Piestewa (q8) and the duplex (q6)
carry dimensions as drawn outlines, not text; q9 is an itemized list;
q10/q11 are images — those get scale only from the model note (PR C) or
manual calibration (PR D), as the plan said.

**Gotchas.** (1) `chainCalibration.samples` is the cluster size, not the
pair count. (2) A `note` attached at sheet level carries 0.7, under-the-
drawing 0.8. (3) `PageRegion.scale` defaults to null so old kits and the
classic path parse unchanged. (4) Nothing consumes `scale` yet — PR C.

---

## 2026-09-13 (b) — Stage 1 UI PR 4: Quote step, Done state, Admin ported

**Shipped (PR 4 of 4, stacked on PR 3). Stage 1 is code-complete.**
- **Quote step** (`QuoteBuilder.tsx`, rewritten): three tier cards (radio
  semantics; click PATCHes `pricing_tier`) with the boxes / doors&fronts /
  drawer-box breakdown; line items as the itemized audit; Adjustments
  (markup, handling) and Shipping (pallets, estimate, override, "I've
  confirmed the shipping cost" checkbox) cards; Total card. Sticky bar with
  the tier total, **the list of blockers** (shipping unconfirmed, unpriced
  lines with a link back to the takeoff, placeholder rates), "Download PDF"
  and "Send quote". Send PATCHes `status=sent` — the SERVER enforces the
  gates — then opens the mailto draft (PDF attach stays manual until the
  Stage 2 email provider). **Done state**: sent/won/lost/expired lock every
  input and tier card, show a green banner with the sent time and "Start
  another job"; More menu offers Mark won / Mark lost when sent, plus the
  CSV exports. Operator-only: pricing-config version, product-line ids,
  "placeholder rate" chips, and the real NEEDS-REVIEW wording render for
  `admin`; everyone else sees "pricing isn't finalized — ask an admin".
- **Admin** (`Admin.tsx`, rewritten on the component library): sidebar with
  `?tab=` routing (`validateSearch` on `/admin`) — Pricing · Branding &
  terms · Freight & reading · Export mappings · Users; Crawler sources
  hidden from the sidebar but routable (account menu › Operator › Crawler
  sources). Pricing editor: sticky save bar with the placeholder-rate count,
  per-line cards, "placeholder" chips, test calculator on `Field`/`Select`.
  Branding: logo upload now goes through `apiUpload` (**bug fix in
  passing**: the old raw `fetch` sent no bearer header, so the upload 401'd
  on the cross-site Railway deploy). Terms/footer save only when dirty.
  Users: form submit, role hints, toasts. Every save toasts.
- Layout: the Admin nav link clears `?tab`; Operator menu gains Crawler
  sources.

**Verified** on the mock API: quote draft (blockers listed, Send disabled),
quote sent (locked Done state), admin pricing / branding / users, light +
dark. `pnpm build` + `pnpm test` green. Not run against the real API.

**Gotchas.** (1) The Send button is disabled purely from the client's
`blockers` list, which mirrors the server gates in `quotes.ts` — if a gate
is added server-side, add it to `blockers` too or the button will look
enabled and the PATCH will 4xx (the toast shows the server's message).
(2) Mark won/lost PATCH `status` with no other gates. (3) Roles still
can't be edited in Users — Stage 2 replaces the allow-list anyway.

---

## 2026-09-13 — Stage 1 UI PR 3: Pages step + Review rework

**Shipped (PR 3 of 4, stacked on PR 2).**
- **API**: `GET /takeoffs/:id` now returns `quote_tiers` (same
  `priceQuoteTiers` call the quote uses) so the review bar shows the number
  the quote will open with. `POST /takeoffs/:id/accept-lines
  {min_confidence?}` marks every line in `[threshold, 1)` as reviewed in one
  UPDATE (replaces the UI's PATCH-per-line loop).
- **Pages step** (`PagePicker.tsx`): readable pages (plan / elevation /
  schedule per the classifier) are PRE-SELECTED — the common case is "looks
  right, go"; "All plans / All elevations / Every page / Clear" shortcuts;
  per-tile type chips (Plan · Elevation · Schedule · Finishes · Skip) replace
  the `<select>`; the primary button counts readable pages only; a "Draw the
  regions yourself" disclosure hands the selection to the wizard via
  `/takeoffs/:id/detect?pages=1,3,5` (`validateSearch` on the route), which
  opens straight on Draw. The wizard uses the shared `Stepper`; the "Detect
  (beta)" buttons are gone from the picker and review headers (the review's
  More menu keeps "Re-read with drawn regions…").
- **Review** (`TakeoffReview.tsx`, rewritten): fixed-height two-pane layout
  (drawing 3fr / breakdown 2fr, each scrolling internally; `SourceBoxPanel`
  gained a `maxHeight` prop). Breakdown grouped by room with per-room qty;
  every cell is a `Cell` (click/tab to edit, Enter or blur commits, Esc
  restores — no more `e`-or-double-click); material/finish sit under the tag;
  confidence is a button that accepts the line; unmatched lines carry an
  inline product `Select` (same PATCH as the old bucket); derived door/front
  faces hide behind "Show doors & fronts" and are summarized per cabinet
  ("2 doors · 1 front"). Filter tabs All / Flagged / Unmatched with counts;
  category legend with quantities; "notes from the read" collapsible = the
  Stage V Flags slot (doc uncertainties + warnings today, per-line flags
  later). **Delete is soft**: the row hides, a toast offers Undo for 8 s,
  then the DELETE fires (pending deletes flush on unmount). Sticky bar: Base
  estimate + Upgraded/Premium, cabinet count, "N to check", "Accept N
  confident" (batch endpoint), and **"Looks right → Quote"** which approves
  then creates the quote in one go ("Approve without quoting" lives in More).
  Keyboard: ↑/↓ (j/k), Enter accept+advance, Del soft-delete, `e` focus the
  row's first field, `?` shortcuts dialog. Materials is a one-line
  `<details>` under the drawing. Failed takeoffs get a plain failure screen.
- Toasts accept an `action` + `ttlMs` (used by Undo).

**Verified** on the mock API (with read images + bboxes + derived faces):
layout at 1440 light/dark, keyboard nav, soft delete + Undo, help dialog,
Pages pre-selection and chips. `pnpm build` + `pnpm test` green. Not run
against the real API.

**Gotchas.** (1) `Cell` commits on blur — one PATCH per edited cell; fine
for review volumes, but don't wire it to anything that re-renders the whole
list per keystroke. (2) The right panel is width-budgeted for ~560 px; adding
a column means removing one. (3) `BoxReviewSection` (legacy
`awaiting_boxes`) is untouched and still uses the old table.

---

## 2026-09-11 — Stage 1 UI PR 2: Jobs list, live reading progress, quotes named by file

**Shipped (PR 2 of 4, stacked on PR 1).**
- **`takeoffs.progress` jsonb** (migration `0009`, applies at API boot):
  `{stage, done, total, message, started_at, updated_at}`; shared
  `TakeoffProgress` / `TAKEOFF_STAGES` (prepare · classify · locate · detect ·
  measure · read · price). Workers write it through `takeoff/progress.ts`
  `setProgress()` at every stage boundary — prepare (thumbnails every 5 pages,
  then classify), staged reads (locate per page, detect per region, measure
  before `buildFromDetections`), image reads, and `priceAndExpand` (so every
  path reports "price"). `resetProgress()` at the start of prepare/extract
  keeps `started_at` per run. Best-effort: a failed write never fails a job.
- **`GET /jobs`**: takeoffs (by `updated_at`) joined to their latest quote
  (`{id, status, totalCents}`) + `selectedPageCount` + `progress`. One call
  for the list.
- **Quotes ↔ filenames** (owner ask: "quote ids don't mean anything"):
  `GET /quotes` rows carry `sourceFilename`; `GET /quotes/:id` carries
  `sourceFilename` + `takeoff_status`. Quotes list and Quote Builder title
  show the job's filename; the hex id survives only as a small mono
  `quoteRef()` (#XXXXXXXX) for support and the PDF email subject.
- **Web**: Jobs page (`Takeoffs.tsx`) — `UploadZone` (drag-drop + picker,
  type/size validation, compact once jobs exist), filter tabs with counts
  (All / Needs attention / In progress / Quoted), one row per job with step
  pill + live progress message, quote total, relative time; row links to the
  right step (pages / takeoff / quote); polls only while a job is processing.
  `ReadingProgress` checklist (PDF: 6 stages; image/spreadsheet: read → price)
  with done/now/next states, counts, elapsed timer — rendered by
  `TakeoffReview` while `processing` and by `PagePicker` while preparing.
  Quote Builder gets an "Open the takeoff" action.

**Verified** in the browser against the mock API (Jobs populated with a live
progress row, Reading screen, Quotes, Quote Builder); `pnpm build` and
`pnpm test` green across the monorepo. NOT run against the real worker —
the first prod job after deploy is the real test of the progress writes.

**Gotchas.** (1) `setProgress` uses `jsonb_build_object(...) || ...` so
`started_at` survives later writes; a plain `.set({progress})` would reset
the timer at every stage. (2) The classic (`STAGED_READS=0`) PDF path only
reports `read` at load and `price` at the end — per-page progress there was
not wired (the path is a rollback knob, not the default). (3) Routes are
still `/takeoffs/:id`; the plan's `/jobs/:id` naming is deferred to avoid
churning deep links while PRs 3–4 land.

---

## 2026-09-10 — product pivot agreed; Stage 1 UI PR 1: design system + shell

**Context.** Owner (Mike) tasked Rida with turning Scribe into a self-serve,
takeoff-only product: sign up → upload → pick pages → review the breakdown →
quote, metered by credits. The staged plan lives in `product-plan.md` (PR #253):
Stage 1 UI rework, Stage V verification layers (whole-set deterministic checks
+ a one-call model reviewer, flags only), Stage 2 accounts (email provider
first, then orgs + tenant scoping — today `GET /takeoffs` returns every row to
any signed-in user), Stage 3 usage ledger → per-page credits → Stripe, Stage 4
beta. All decisions closed: style direction A, Google + magic link + optional
password, 1 credit = 1 page read, freight gate kept, prospector hidden (code
stays), name stays Scribe, Admin ported as the control panel. PRD §2/§3 are
superseded on these points; `PRD.md` itself still needs the amendment.

**Shipped (PR 1 of 4).** Web only, no API change.
- `styles.css`: runtime token set (vellum ground, ink, redline accent,
  blueprint blue, semantic good/warn/bad, fixed cabinet-category palette)
  mapped into Tailwind 4 via `@theme inline`, so utilities like `bg-paper` /
  `text-muted` flip with the theme and pages never need `dark:`. Three theme
  states (un-stamped follows the OS; `data-theme` light/dark wins), toggle in
  the top bar, preference in localStorage. Archivo (headings, `wide` utility =
  wdth 110) / IBM Plex Sans / IBM Plex Mono from Google Fonts with fallbacks.
- `components/ui/`: Button (primary/default/quiet/danger, sizes, `loading`),
  Input/NumberInput/Select/Textarea/Field, Badge + **StatusPill**, Card +
  SectionLabel, PageTitle, ToastProvider/useToast, Skeleton(Rows), EmptyState,
  Stepper (the §2 job stepper), Dialog, Kbd. `ui.tsx` is a re-export shim so
  every page keeps compiling; `statusTone` kept as a legacy helper.
- `labels.ts`: one `labelFor(status)` / `toneFor(status)` map (takeoff, quote,
  prospect, source enums → "Reading", "Choose pages", "Needs review", …) and
  the category palette shared by `BoxOverlay` (concrete hex — the sheet under
  the dots is always white) and the chrome (`categoryDotClass`).
- Shell (`Layout.tsx`): Jobs (`/`, the old Takeoffs list) · Quotes · Admin
  (admin only); Dashboard moved to `/dashboard` and Prospects reachable only
  from the account menu's Operator section; account menu with sign-out; new
  sign-in screen. Review/detect routes are full-bleed, everything else a column.
- Mechanical sweep: 149 hard-coded zinc/blue/red/amber classes across 13 files
  → token classes (scoped to class strings only). Table heads are mono
  uppercase. Every raw status enum on screen → `StatusPill`. Toasts on every
  mutation in Takeoffs / PagePicker / TakeoffReview / QuoteBuilder (approve,
  patch, delete and create-quote failures were silent before). Jobs list polls
  only while a row is `processing`; skeleton + empty state.

**Verified** against a throwaway mock API (no DB, no auth) in the browser:
Jobs (populated + empty), Review, Pages, Quote Builder, account menu, light and
dark. `pnpm build` (tsc + vite) green. Not exercised against the real API.

**Gotchas.** (1) Tailwind 4 `@theme inline` is what makes var-backed utilities
work; a plain `@theme` would bake the light values. (2) `bg-white`/`text-white`
were swept to `bg-paper`/`text-paper` — on the accent button that is fine in
both themes, but anything drawn OVER THE DRAWING IMAGE must keep concrete
colors (see `categoryHex`). (3) The `Detect (beta)` wizard route and
`awaiting_boxes` legacy path are untouched; PR 3 folds them in.

---

## 2026-08-18 — plan runs decompose into units; dots replace boxes; a door swing was being priced

**Context.** Staged reads scored ~0.55 F1 on elevation inputs but ~0.26 on
plan/sketch inputs: a plan draws each wall's casework as one unbroken band, so
the measure stage priced a whole counter RUN as one cabinet while gold counts
manufactured units.

**The blocker nobody had measured: the measure stage cannot READ a plan.** A
36x24 sheet renders at ~37 DPI to fit the model's 1568px cap — its dimension
strings are a smudge at that size, so "split the run by its printed length" was
impossible from the page image. The detect-stage REGION crops are ~160-200 DPI
and perfectly legible. So the measure call now carries the plan-region crops as
extra images (annotated with the same marker numbers, `MEASURE_MAX_CROPS = 8`),
alongside the pages it already sent.

**Shipped (measure-v6 / detect-v5).**
- `takeoff_detections.kind` (migration `0008`) — 'plan' | 'elevation', written
  by `stagedExtractPdf` from the located region. NULL = wizard-drawn, treated
  as elevation. This is what tells the measure stage which markers are runs.
- Plan markers are flagged `[PLAN RUN — decompose into units]` and come back
  with `run_length_in` + a `units[]` array; `mergeMeasuredLines` emits ONE LINE
  PER UNIT (never the run), slicing the run's bbox along its long axis in width
  proportion (`sliceRunBbox`, shared) so each unit keeps a visual anchor. Guards:
  16 units/run cap, zero-width units dropped, warnings when a run comes back
  undecomposed, over-splits past its printed length, or fills under 25% of it.
  `mergeMeasuredLines` now returns `{lines, warnings}`.
- Layout rules ported from `ESTIMATE_SYSTEM` (appliance-specific units, DW/fridge
  are GAPS not cabinets, one corner cabinet where runs meet, standard widths,
  arithmetic must close on the printed length). **Vanities stay ONE unit per
  drawn run** — ESTIMATE_SYSTEM v3's rule, NOT the gated DECOMPOSE suffix's
  per-sink split (Piestewa gold prices a 77" double vanity as one line).
- detect-v5: on plan views box the RUN, never a door swing / its callout
  ("NEW 2668") / a lone fixture / a dimension string. `stripDoorCallout` (shared)
  also scrubs a door tag out of a name that survived.
- `annotatePage` now measures its own image instead of trusting the caller's
  inches x DPI (a 1px rounding difference made sharp refuse the overlay).

**Measured, ZERO API** (staged kit harness, assistant as the vision model;
baselines kept as `~/Desktop/Scribe Testing/staged-kits/qN-baseline-v5/`):
Piestewa 0.21→**0.44**, Stephens 0.07→**0.30**, Walters 0.21→**0.33**,
Kondylis 0.04→**0.21**. Plan-kind mean **0.13 → 0.32**; whole 18-quote set
**0.42 → 0.47**. The other 14 kits replay through the new merge code with
IDENTICAL scores (the path is inert without a plan-kind marker). Precision rose
as well as recall — decomposed units are standard widths keyed to a printed
length, where a single run line was a category default.

**Owner-reported false cabinet, root-caused (takeoff a6e317a3, Piestewa).** The
"bath vanity NEW 2668" line's box sits exactly on a DOOR SWING tagged NEW 2668
(2'-6" x 6'-8") in Bath 3 — a false cabinet, not a rendering offset. Proof that
the geometry is fine: on the same page the sink base, dishwasher, range and
microwave boxes all land dead on their objects. detect-v5's exclusion list is
the fix; that takeoff needs a re-run to clear the existing line.

**Review UI: zoom/pan, and dots instead of boxes** (owner: "bounding boxes are
looking kindof bad", then "give the pdf more control to zoom in on parts of
it"). `BoxOverlay` now owns a scroll viewport whose inner width is
`zoom x 100%`, so panning is native scrolling and every coordinate stays in
image space (the SVG viewBox keeps mapping; nothing needed a transform matrix).
Zoom 1-10x via buttons or ctrl/cmd+wheel anchored at the cursor; drag the sheet
to pan (hold SPACE to pan while the beta wizard is in draw mode, which is
always); "Fit" resets. Selecting a line SCROLLS ITS CABINET INTO VIEW — at 4x
zoom the dot is otherwise off-screen, which would have made the whole
click-a-line-to-find-it flow useless. Dots, labels and handles are sized off
the SVG's measured width, so they stay constant on screen at any zoom. Verified
by driving the real component in a throwaway vite sandbox: zoom anchoring lands
on the exact expected scroll offsets, drag-pans are 1:1, space-drag in draw mode
pans without creating a box.
`BoxOverlay` draws one category-colored DOT at each cabinet's centre; the
rectangle, its label and the resize handles appear on hover/selection, where
they are useful. Everything else is unchanged — click-to-select still syncs
with the line table, drag moves, corners resize, draw-new-box still draws.

**Gotchas.** (1) Q2/Q16 sit in the plan-only score bucket but their kits locate
an ELEVATION region, so decomposition never fires there — both stay 0.00, an
under-detection problem on sketches. (2) Nothing dedupes markers across
overlapping regions: Walters is a mirrored duplex whose located regions
overlap, so a run can still be boxed twice. (3) Tall heights still default to
84" where gold wants 96" — outside the ruler's ±6".

---

## 2026-08-17 — beta detect wizard → staged reads become the DEFAULT pipeline

**Context.** Owner wanted takeoff reading to mirror TakeoffBOT's interaction
(reference recording): draw over a plan, get labeled cabinet boxes; then
staged it further — segment → boxes → detect (no dims) → one whole-input
measurements pass — first as a human wizard, then as the automated pipeline.

**What shipped (PRs 240, 242–247).**
- Beta detect view `/takeoffs/:id/detect` → 4-step wizard (Pages/Draw/Detect/
  Build); detections in new `takeoff_detections` (migrations 0006/0007);
  jobs `beta_render`/`detect`/`beta_build` on the existing queue; builds run
  `replaceLines` → `priceAndExpand` (replace-all, owner choice; `review →
  processing` transition added).
- Measure pass: whole PDF sent (marker pages annotated set-of-marks via
  sharp, others as context), per-marker proximity dim grounding
  (`dimsNearRect`, measure-v5), raw responses persisted to
  `takeoffs/{id}/beta/measure/response-N.txt`.
- **Fontconfig incident**: first prod run defaulted all 23 cabinets — worker
  image had no fonts, SVG marker numbers rendered blank (Railway logs showed
  `Fontconfig error`). Fixed: fonts-dejavu-core in workers Dockerfile (#243).
- Labels: detect-v3/v4 + measure-v4 forbid bare-number names;
  `meaningfulTag()` backstop; Quote Builder priced lines show item identity.
- Materials card on review (carcassSqft/materialStats, 4×8 @15% waste).
- **Staged auto-extraction** (`stagedExtractPdf`, #247): auto-seeds located
  regions as detections, elevation-primary region routing, then the wizard
  jobs. **Now the DEFAULT** (`STAGED_READS=0` reverts to classic).
- Zero-API staged kit harness (`prepare-staged.mjs`/`replay-staged.mjs`):
  full 18-quote test-set run with assistant-as-model — **mean F1 0.42 vs
  0.32 classic; elevation-rich ~0.55** (Maurer 0.78, Boyle 0.75), plan-only
  ~0.26. Kits + ANALYSIS.md: `~/Desktop/Scribe Testing/staged-kits/`.

**Open items.** (1) Plan-only run→unit decomposition in the staged measure
stage — biggest gap; classic estimate mode still stronger there. (2) Carcass
granularity conventions (merge multi-bay vs split stacks) differ per
manufacturer. (3) Same-model A/B via `score-reading.mjs` once deployed.
(4) Q5/Q21/Q22 kits are partial page selections — extendable.

---

## 2026-08-13 — quote tier persisted: one number everywhere (migration 0005)

Owner found the quotes LIST showing $34k while the Quote Builder offered
$49.8k–$65k tiers for the same quote (Wantoch). Cause: two pricing engines —
the stored `subtotal/total` came from the legacy per-line `runPricing` at
create/patch time, while the builder displayed the live `priceQuoteTiers`
estimate (CabinetNow-style boxes + doors-ft² + drawer-box hardware) with the
tier picker held in CLIENT STATE only, never persisted. The tier engine is the
validated one — on the Wantoch read it landed within 6.3% of the real $53,232
quote; the per-line number was −53%.

Now: `quotes.pricing_tier` ('low'|'medium'|'high', default medium, migration
`0005_quote_tier.sql`); stored subtotal/total derive from the persisted tier
(+ markup/handling/freight) at create AND patch; clicking a tier in the
builder PATCHes `pricing_tier`; the PDF defaults to the persisted tier
(`?tier=` still overrides). The per-line run remains for freight, the
itemized `line_prices` audit detail, and the send gates. **Gotcha:** quotes
created BEFORE this change keep their stale per-line totals until any PATCH
(tier click or field edit) re-prices them.

**Same day — Wantoch line-item audit (Scribe quote PDF vs the real packet),
the session's key evidence:** ignoring the packet's flat −10% discount, Scribe
Upgraded $56,878 vs real $53,232 subtotal (+6.8%; Shaker base −6.3%) — but the
total is right for partially wrong reasons: ~$8.7k of PHANTOMS (a $1,384 "TV
cabinet" that is the open wall gap between the dining towers; $4,103 of
living-room talls that are the dining towers re-counted from another view;
$3,168 of 1.5" fridge END PANELS priced as full 24×84 cabinets; +3 island
bases from plan+elevation double-count; a ~$3.3k bedroom built-out not in the
real quote) roughly cancel the UNDER-reads (five deep-wall stacks read 33"
tall vs real 52.5–54"; missed 33×49.5 appliance garages ×2 and the 46.25"
pantry pair). Fix directions ranked: end-panel/panel category handling;
cross-view/room reconciliation; open-span phantom; dimension grounding for
heights. Also: this packet numbers every unit (1–50) with a keyed box list —
the ground-truth quality to collect more of for the test set.

**Session wrap (PRs this session):** #233/#234 two-step review + page tabs,
#235 box gate removed → interactive review, #236 gated elevation-primary +
kit A/B, #237 sideways-content normalization, #238 quote tier persisted. All
merged; branch `claude/scribe-two-stage-review-24ca21` fully in main.

**Open items for next session:** (1) decompose + DIM_SKELETON A/B — needs
fresh API reads (~$5), targets the convention clash + height misreads; (2)
deterministic check layer (width-sum vs printed run length; bbox overlap/
aspect/coverage checks); (3) room-keyed cross-view reconciliation; (4) panel
category handling; (5) owner collecting better ground-truth packets
(numbered-unit style like Wantoch).

---

## 2026-08-11 — box gate removed: 2-step flow (pick pages → interactive review)

**Owner feedback while testing live:** the separate box-review stop duplicated
the review screen. The flow is now TWO steps — choose pages → approve takeoff —
and the review screen itself is the interactive editor showing each detected
cabinet with its box on the source image. Supersedes the "always blocking box
gate" below.

- **`awaiting_boxes` is dead as a flow state** (stays in the DB CHECK and in
  legacy code paths for rows parked there: the `finalize` job, the
  `finalize-boxes` endpoint, and `BoxReviewSection` all remain but nothing new
  enters that state). The extract stage — and the text-schedule prepare path —
  now run `priceAndExpand` immediately. Status flow:
  `processing → awaiting_pages → processing → review → approved`.
- **Review screen = interactive editor:** `SourceBoxPanel` (tabs "Page 1",
  "Page 2"…) replaces the static source image whenever read images exist —
  box↔line selection sync both ways, drag/resize (PATCH bbox), draw-new-box →
  priced line with faces, ✕ button / Delete key removes a line (+ its faces).
  Spreadsheet takeoffs keep the static panel (no read images).
- **The API keeps the priced list consistent per edit:** faces link to their
  cabinet via `raw_model_output {expanded: true, parent: <lineId>}`. A PATCH
  touching pricing-relevant fields re-runs `matchLine` and re-derives that
  cabinet's faces; DELETE cascades them; POST /takeoff-lines now also works at
  `review` (matches + expands immediately). A patch carrying
  `product_line_id`/`resolved_params` (the unmatched-bucket manual assignment)
  is NEVER re-matched over.
- **Gotchas:** (a) faces created by finalize BEFORE this change lack `parent` —
  editing a cabinet on those takeoffs re-adds faces without removing the old
  parentless ones (the ~3 takeoffs in `review` as of today; re-run them if
  edited). (b) The face refresh is gated on sourceKind pdf/image — spreadsheet
  takeoffs never expand.

**Same day — sideways-content normalization (pdf.ts):** the Braun webdownload
set draws landscape sheets ROTATED on portrait pages with NO /Rotate flag
(mupdf honors /Rotate — verified; these pages are simply drawn sideways), so
elevations rendered sideways and label reads garbled ("Oven Fridge Tall 18"
for "36\" OVER FRIDGE"). `openPdf` now detects each page's dominant text
orientation from the text layer (vertical-vs-horizontal bbox aspect, weighted
by text length; the baseline anchor's position picks CW vs CCW) and serves
EVERYTHING — dims, full renders, region crops, text fragments — in normalized
upright space; callers unchanged. Conventions (probed empirically, see
pdf-rotation.test.ts): `mupdf.Matrix.rotate(90)` turns the raster CLOCKWISE;
bottom-to-top text (anchor at bbox bottom) needs 90, top-to-bottom needs 270;
region pixmap bboxes shift by −rawH (rot 90) / −rawW (rot 270) because the
device box lives in post-transform space. Harness scripts import openPdf from
dist → parity automatic. Workers tests 13 → 21.

**Same day — router A/B on the read kits (zero API), owner prompt:** on the
Braun doc the plan-first router kept 5 coarse plan guesses and dropped 3 fully
LABELED elevations ("28\" SINK BASE"…). Owner proposed elevation-primary
(frontal view = unit identity, plan = layout/widths). Implemented gated
`ROUTER_ELEVATION_PRIMARY=1` (schedule > elevation > plan; implies the
tolerant merge so plan-only units like islands are re-admitted) and replayed
all 10 kits: baseline 0.328 / `ROUTER_TOLERANT_MERGE=1` **0.379** /
`ROUTER_ELEVATION_PRIMARY=1` 0.376 macro F1. Verdict: recovering dropped
elevations is the whole win (Q5 0.21→0.42, Q22 0.22→0.33, Q24 0.38→0.57);
WHICH view is primary is a wash (only Q22 differs, slightly favoring
plan-primary). Recommendation: turn on `ROUTER_TOLERANT_MERGE=1` in prod
(scribe-workers env — still an owner action, still "API confirm pending");
keep elevation-primary gated for future A/B.

---

## 2026-08-10 — two-stage human review shipped: page-picker + bounding-box gates (box gate since removed — see 2026-08-11 above)

**Owner decision (2026-08-05): both gates are ALWAYS BLOCKING** — no auto-pass,
superseding the autonomous-only flow. New status flow:
`processing → awaiting_pages → processing → awaiting_boxes → review → approved`
(+ `failed`; `extracted` stays a dead legacy value — old rows may exist, don't
repurpose it).

**Shipped (branch `claude/scribe-two-stage-review-24ca21`):**
- **Migration `0004_review_gates.sql`** — the `takeoffs` status CHECK is
  DROPPED and re-added with `awaiting_pages`/`awaiting_boxes` (boot-migrate
  applies it on deploy). New columns: `takeoffs.selected_pages` jsonb;
  `takeoff_lines.bbox` (px of the read image), `read_image_key`,
  `read_rect` ({x0,y0,x1,y1} PDF points + dpi).
- **Worker split** (`process.ts`): one job → three — `prepare` (every-page
  72-DPI picker thumbs to `takeoffs/{id}/thumbs/`, doubles as classify input →
  `awaiting_pages`), `extract` (reads ONLY `selected_pages`, user tag override
  replaces the classifier's class via shared `selectRelevantPages` →
  `awaiting_boxes`), `finalize` (re-match every human-approved line +
  `expandToComponents` → `review`). Legacy `process` jobs still route
  (in-flight across the deploy); **spreadsheets stay ungated** (straight to
  `review`); **text-layer schedule PDFs skip only the page gate** and stop at
  `awaiting_boxes` as a list-only review (no bboxes).
- **Expansion + pricing MOVED to finalize.** Extraction inserts BOX-level
  lines only — no `matchLine`, no faces — so faces always derive from the
  human-corrected boxes. Finalize marks derived faces
  `raw_model_output.expanded=true` and deletes them first on re-run
  (idempotent). Eval fixtures now snapshot box-level lines at extract time.
- **Read-image provenance:** every image actually sent to the model persists
  at `takeoffs/{id}/reads/p{page}-c{cand}-{full|rN|rN-tK}.png` — per
  CONSENSUS CANDIDATE, because room/region locate differs per read; the chosen
  read's boxes always match their own pixels. Router/dedup drop lines, not
  boxes — surviving lines keep their provenance.
- **Prompts** demand `bbox_2d` per line → versions bumped to `estimate-v5` /
  `extract-v2` (reading-ruler comparisons cross a version boundary here).
  `CabinetLineItem.bbox_2d` parses with `.catch(null)` — a malformed box can
  never drop a line. **BBoxes are advisory-quality** (July spike showed loose
  boxes): visual anchors the reviewer corrects; box edits are visual-only, the
  inch fields drive price.
- **API:** `POST /takeoffs/:id/pages` (awaiting_pages→processing, enqueues
  extract), `POST /takeoffs/:id/finalize-boxes`, `POST /takeoff-lines`
  (reviewer-drawn box → new line, confidence 1, reviewerEdited), `PATCH
  /takeoff-lines/:id` accepts `bbox`, signed thumb/read-image URL routes with
  existence/slug guards. Transitions guarded by shared `canTransitionTakeoff`.
- **Web:** `/takeoffs/$id/pages` (PagePicker — thumbnail grid, click-select,
  per-page type select prefilled from the classifier; the class is only SENT
  when the user changes it). The box gate is NOT a route: `TakeoffReview`
  renders `BoxReviewSection` inside `/takeoffs/$id` while status is
  `awaiting_boxes` (owner feedback 2026-08-11 — the views are similar, keep
  review one page). Read images are TABBED with human labels ("Page 1",
  "Page 2"; a/b suffix when a page has several crops — also owner feedback,
  after trying a stacked layout); clicking a line switches to its image, one
  SVG `BoxOverlay` in image-natural coords, drag/resize/draw/Delete-key,
  always-editable line rows, "Finalize boxes →". `TakeoffReview` still
  forwards `awaiting_pages` to the picker.

**Gotchas for future sessions:**
- `tokensUsed` now ACCUMULATES across stages; the `TakeoffBudget` cap is
  per-STAGE, not per-takeoff.
- A selected page whose effective class isn't readable (`other`/cover) is NOT
  read — the picker UI says so; tags decide HOW a page is read.
- The offline harness (`estimate-floorplan.mjs`) stays single-stage by design
  but imports the same prompts/extractor from dist, so it measures the bbox
  prompt automatically after `pnpm build`.
- Tests: shared 142 / workers 13 / pricing 44 all green. NOT yet e2e-verified
  against the live API (needs the backtest key + ~$0.50; run upload → pick →
  boxes → finalize → approve on a 1-page real PDF when approved).

---

## 2026-08-05 — step attribution via zero-API read kits; router merge + 3 fixes measured

**Context:** Owner pivoted to the agentic-reading path with a diagnose-first
directive and ZERO API spend (all vision reads on the owner's plan — in-session
+ subagents — via the new read-kit tooling). Detector PoC (H3) closed first:
YOLOv8n on ~240 hand-labeled boxes = recall 37%/precision 5%, and halving the
training data barely moved it ⇒ data-starved by orders of magnitude, not
incrementally; report in `~/Desktop/Scribe Testing/detector-poc/PoC-summary.md`.

**Shipped — offline instrumentation (branch `scribe/agentic-reading-diagnosis`):**
`scoreReadingDetailed` (per-unit gold→MISS / pred→PHANTOM alignment + silent-drop
counts); `prepare-reads.mjs`/`replay-reads.mjs` (pipeline split at every vision
boundary into exact image+prompt request files; replay runs the REAL
`processExtractionResponse` → router → scoring); harness grounding drift fixed
(large-format estimate paths now pass grounding like prod).

**Attribution (10 quotes, manual Sonnet-grade reads, `reading-step-attribution.md`):**
regime decides the score — elevation/passthrough quotes 0.42-0.80, EVERY
plan-regime quote 0.19-0.31. Ranked losses: (1) router role-drop + plan-first
precedence (Q22 dropped 36/49 read lines incl. the whole kitchen elevation; Q5
9 directly recoverable); (2) decomposition-convention clash vs packet pricing
(vanity-as-one-unit etc., ~25-30 misses + ~20 phantoms); (3) input ceiling —
~60-80/260 gold units NOT depicted in the inputs at all (Q1 missing interior
elevation sheets, Q2 sketch, Q8 plan-only); (4) near-duplicate page re-renders
(Q24 6/8 phantoms); (5) bugs: `isNonBoxCasework` regexed over NOTES (deleted a
real tall whose notes said "crown", Q13), lenient parse dropped lines with zero
telemetry. Sub-100-DPI illegibility (7b) was NOT dominant in this pass (caveat:
manual readers could re-inspect; one-shot API cannot).

**Fixes + re-measure on the SAME saved reads (zero API):**
- `isNonBoxCasework` now judges by TAG (notes only as fallback) — ungated bug fix.
- Schema-dropped-line count now surfaces in uncertainties — ungated.
- `ROUTER_TOLERANT_MERGE=1` (gated): keep authoritative role, collapse
  near-duplicate page re-renders (≥80% unit-multiset overlap), then re-admit
  demoted-role units no kept unit matches within ruler tolerance (cat, ±3"w/±6"h).
- `ESTIMATE_PROMPT=decompose` (gated, unmeasured — needs new reads): packet-style
  component decomposition rules.
Result on the 10-kit worst-heavy subset: **macro F1 0.336 → 0.379 (+0.043)** —
Q5 0.21→0.42, Q24 0.42→0.57 (countErr +71%→0), Q22 0.22→0.33, Q8 0.23→0.31;
Q13 0.80→0.69 (regex fix un-hid open-shelving lines the bug had been
suppressing — prompt-side fix, not a regex revert). Tests: shared 125 / workers
13 / pricing 44. NOT yet API-confirmed; kits are N=1 manual. Next: API
confirmation run of ROUTER_TOLERANT_MERGE vs the 0.396 baseline when credits
allowed; decompose-prompt arm needs fresh reads; local Qwen3-VL detector test
runbook staged at `detector-poc/QWEN-TEST-README.md` (separate session).

---

## 2026-07-06 — from-zero study: labels v3 (header-driven packet parsing) + gated DIM_SKELETON grounding

**Context:** Owner directive: "work from 0 — upload an image, preprocess it to be
most suitable, prompt Claude; look at the files, THEN plan." The Anthropic API key
was **out of credits** all session (also why CI is red — owner ack'd), so all
validation ran on the owner's Claude plan: Claude-in-session did the vision reads,
and the scorer (`scoreReading`, pure) ran offline. Merged PR #226 first (prior
session's ruler fix + plateau evidence + report), then branch
`scribe/labels-v3-dim-skeleton`.

**From-zero findings (looking at the actual 21 inputs):**
- **17/21 inputs carry machine-readable printed dimensions WITH positions** (PDF
  text layer via `pageTextFragments`; images have legible handwritten dims). The
  drawings print the answer: Q7's island elevation carries its own cabinet split
  (`6|27|24|24|27|6` under `124"`). This is localization for FREE — the thing the
  VLM bbox spike proved it can't self-generate.
- **Manual dimension-grounded reads** (me as the vision model, dim chains as
  ground) on Q7/Q14/Q8/Q11/Q2, scored vs the then-current labels: Q2 0.00→0.30,
  Q8 0.36→0.40, others ~flat — and the flat ones exposed that **the ruler was
  still lying**, which became the session's main work.

**THREE MORE RULER BUGS (all fixed, labels v3):**
1. **Cab#-as-width:** packets with a leading `Cab# (QTY)` column (Q11 "Steady
   Ground") were parsed positionally — first numeric = width — so Q11's gold was
   garbage ("Sink Base, 4 inches wide"; real: 36/18/15/33/45/31⅞).
2. **Reprinted schedules:** CabinetNow packets print the CABINET BOXES table once
   per door-style option (Q14: pages 13 AND 15, identical) → carcasses doubled.
3. **Boxfix over-kill:** the (d)-session regex `/cabinet door|drawer front/`
   deleted real **"Wall Cabinet Door Over Door …"** carcasses — all 7 of Q14's
   wall cabinets were missing from truth.

**Shipped — `extractCabinetSchedule` v2 (shared `schedule.ts`, prod Class-1 path
AND labels):** header-row detection with boundary-range column mapping (numeric
cells are right-aligned; leftmost column captures its outdented names);
**width-anchored record assembly** (every record has exactly one width; names wrap
above AND below it — nearest-anchor attachment handles both); **money-header
tables skipped** (priced DOOR & DRAWER LIST) and barred from the legacy fallback;
**cross-page header carry** (a table's continuation rows on the next page parse —
recovered HALF of Q8's truth: pantry talls, the 68" wall, the 77" double vanity);
**reprint dedupe** (identical page row-multisets); **Qty column** honored (Q6
condo = qty-2 rows); filler-only pages don't qualify as schedules. Drawer-box
hardware ("Dovetail Drawer Box", glide kits) added to `isNonBoxCasework` — also
stops prod box-pricing them. End-anchored door-component filter in
`extract-labels.mjs`.

**Labels v3 result:** 269 → **299 units across 18/21 quotes** (Q16 format gap
closed; Q15/Q19 no packet; Q17 still a format variant). Q14 now exactly matches
its packet (13 units incl. the 7 walls); Q11/Q8/Q6 verified against packet text.
**Every pre-v3 baseline is invalid** — the F1 0.27→0.32 story was measured on a
broken ruler both times. Re-baseline vs labels v3 needs API credits.
Zero-regression verified: the Class-1 path fires on NONE of the 21 input drawings.
Old labels kept: `labels.pre-v3.json`, `labels.pre-boxfix.json`.

**Shipped — DIM_SKELETON grounding (gated, `DIM_SKELETON=1`, default OFF):**
shared `dim-skeleton.ts` — `parseDimInches` (feet-inches/fractions/decimals),
collinear chain clustering with sheet-grid-ruler suppression, room/fixture labels,
`buildDimGrounding` → structured prompt block (chains + "assign each segment to a
cabinet OR an opening" + "the same value sequence in multiple views is the same
cabinets — count once"). Wired through the existing `extractPage opts.grounding`
hook in `process.ts` (estimate paths) and the harness (supersedes the flat
`GROUND_READING` dump when set). Verified on real Q7/Q14 text layers.

**SCOPE-SUBSET finding (owner decision needed):** Q7's packet = **15 of ~27 drawn
cabinets** (sink wall + island customs + glass towers; butler pantry + part of the
built-in wall NOT purchased). Nothing in the drawing marks the purchased subset,
so a perfect full-drawing read caps well below F1 1.0 on such quotes. Autonomous
quoting needs intake scope input, CRM context, or a quote-the-whole-drawing
policy — not a reading fix.

**Manual reads vs labels v3:** Q11 0.61 / Q7 0.47 / Q14 0.44 / Q8 0.36 / Q2 0.23
(pipeline baselines vs v3 unknown until credits return; the manual reads bound
what dimension-grounding can deliver).

**Tests:** shared 112 (14 new) / workers 13 / pricing 44, builds green.

**SAME-DAY ADDENDUM — the A/B ran (owner bought credits on a new BACKTEST-ONLY
key; key lives only in gitignored `.env`s, never deploy/commit it).** Three arms,
N=1, 18 quotes, labels v3, ~$25 spend:
- **TRUE pipeline baseline: F1 0.396** (R 35% / P 46%, size-err 1.4") — the
  "0.32 plateau" was substantially ruler artifact. Per class: labeled 0.49 >
  sparse 0.39 > arch 0.32 > image 0.20 ≈ scan 0.18.
- **DIM_SKELETON strict 0.378 / additive 0.382 → net wash; gate stays OFF.**
  Consistent structure: +0.04..+0.09 on mid/large structured docs (Q3/Q5/Q6/Q8/
  Q11/Q20/Q22) and size-err 1.4→0.8", but small sparse-chain docs get POISONED
  (Q16 0.50→0.00, Q24 0.53→0.22, Q13 0.29→0.00 — same pred count, zero matches:
  the model re-sizes real cabinets to wrong chain values). An ideal
  chain-richness gate nets only ~+0.01 — within N=1 noise.
- **Conclusion:** one-shot Sonnet cannot bind flat-text (x,y) dim chains to
  pixels; the identical information read agentically (manual multi-crop Claude
  reads) scored micro-F1 ~0.44 over 7 quotes with class wins arch 0.17→0.50 and
  sketch 0.11→0.61. The bottleneck is the ONE-SHOT ARCHITECTURE, not the
  information or the model. Next: gated agentic read path (crop/zoom tool loop),
  and a deterministic post-hoc width-snap to salvage the sizing gain risk-free.
- Ops note: a mid-run laptop sleep killed 3 in-flight quotes (rows written as
  ERROR) and silently degraded others — spliced clean reruns before comparing;
  `caffeinate -w <pid>` now wraps long runs.

---

## 2026-07-01 (d) — H3 decided: prompt/vision-only (owner); two levers measured on the ruler

**Context:** Session to "decide/execute the DETECTOR path." Two hard constraints
emerged from the owner: (1) target is **fully autonomous auto-send** (no
human-in-loop, so a send-gate that defers to a human is OFF the table); (2)
**prompt/vision-API ONLY** — "I'm not a cabinet guy to label myself; it needs to
be a prompt to Claude or a vision API." That **kills the trained-detector path**:
a YOLO-style detector needs localized (bbox) training data, the 361 labels carry
ZERO localization (fields: tag/category/w/h/d/qty/raw only — verified), and a
spike proved the VLM can't self-generate usable bboxes (Q8 overlay
`~/Desktop/Scribe Testing/q8-vlm-bbox-spike.png`: 18 loose run/zone boxes, several
on title block/legend/empty rooms — too wrong to bootstrap labels). So there is no
prompt-free path to a dataset, and the owner won't hand-label ⇒ **stay on
prompt/vision, tune against the existing answer key (packets) via the ruler.**

**Reading baseline reconfirmed (5-quote subset Q1/2/8/14/22, N=1):** OVERALL
recall 23% / precision 42% / **F1 0.28** — matches the documented 0.27. **Key
pattern: every quote UNDER-reads** (countErr −35/−68/0/−53/−59%) and preds
**plateau ~13–19 boxes regardless of job size** (Q8 14→14 fine; Q14 40→19; Q22
44→18). Post-router the dominant failure has flipped from over-read to
**under-read on big/dense jobs.**

**Lever 1 — stronger model (Opus 4.8 vs Sonnet-4-6 on the read): NO WIN.** Added a
`VISION_MODEL` env knob (`extract.ts`, defaults to `SONNET_MODEL`; also had to omit
`temperature` for Opus-4.8 which 400s on it). Head-to-head: Opus roughly
equal-to-worse (Q8 29→36% recall but Q1 30→25, Q2 16→0; size-err dropped 1.7→0.9"
but recall/precision flat). **Confirms detection ≠ model capability.** Prod default
unchanged.

**Lever 2 — router "merge-not-drop" (gated `ROUTER_MERGE_ROLES=1` in `routeByPageRole`):
direction confirmed, naive impl insufficient.** DIAGNOSIS (smoking gun, Q14):
`regime=plan kept=16 droppedOtherRoles=33`, truth 40 — the pipeline READ 49
cabinets and the router **threw away 33** to keep the plan's 16. The router was
tuned on the lossy $-metric (19 boxes priced close, so "drop elevations" looked
right); the per-line ruler shows those "dupes" are largely REAL cabinets. Merge
probe (keep all roles, `collapseCrossViewDuplicates` across them): Q8 recall
29→**50%**, Q14 count 19→33 (toward truth 40) — BUT Q14 recall stayed 20%
(recovered elevation cabinets don't match the packet sizes/labels within tolerance;
diff-room-label dupes don't collapse) so precision fell 42→24. **Net: a wash on the
subset — real win on Q8, precision hit on Q14.** The router role-drop is the single
biggest recall leak, but the fix must be COMPLETENESS-AWARE (SCR-007 box-face-area
yield-guard: only demote elevations when the plan is actually complete) + cross-view
size-matching so recovered cabinets COUNT instead of adding noise.

**Shipped (this checkpoint commit, branch `claude/reading-accuracy-prompt-levers`,
NOT merged — no deploy):** `VISION_MODEL` knob + Opus temperature fix
(`extract.ts`); gated dormant `ROUTER_MERGE_ROLES` experiment (`regions.ts`). Prod
default behavior unchanged; tests green (shared 98). Reusable A/B infra:
`labels-subset.json` (5 quotes spanning classes), `reading-{sonnet,opus,merge}-subset.csv`.

**CORRECTION — the RULER was polluted; re-baselined (same session, keep-improving):**
Chasing the "under-read" lever exposed that the ground-truth LABELS themselves
counted non-boxes. The packets carry a separate priced **"DOOR & DRAWER LIST"**;
`extractCabinetSchedule` slurped those `"<style> Cabinet Door"`/`"Drawer Front"`
rows as cabinets (Q14 40 incl. 34 doors; the real job is ~6 carcasses, doubled
across 2 style options). Labels also kept **fillers/end-panels** that the reader
deliberately drops (`dropNonBoxCasework` runs on preds before scoring) — truth had
lines the reader can't emit, deflating recall. **Fix (`extract-labels.mjs`):** count
the SAME priced box the reader does — `isCabinetBox` = `!isNonBoxCasework` AND not
`/cabinet door|drawer front/i`. Verified precise: real door-config cabinets ("Wall
Pair Door", "Base 2 Door", Q21's 49 pair-door boxes) survive. Labels 361→**269**.
Old labels saved to `labels.pre-boxfix.json`.

**TRUE baseline (clean ruler, all 17, N=1) → `reading-scorecard-clean.csv`:**
**recall 41% / precision 31% / F1 0.32** (the reader was UNDER-graded before). Class:
sparse 0.56 > labeled 0.41 > scan 0.35 > image 0.19 ≈ arch 0.17 > image/sketch 0.11.
**The failure FLIPPED: dominant problem is now OVER-read / low precision**, not
under-read — Q7 +329% (30 vs 7), Q14 +183% (17 vs 6), Q24 +150%, Q3 +100%; a few
under (Q2 −87% image, Q23 −65%, Q13 −55%). Notably Q21 (48 vs 49) & Q10 (13 vs 14)
have near-perfect COUNT but F1 ~0.47 → the residual is SIZE/IDENTITY matching, not
counting. This **invalidates the `ROUTER_MERGE_ROLES` direction** (merging adds boxes
→ worsens the now-dominant over-read); keep it gated/dormant. The earlier "under-read
diagnosis" above was a label artifact — trust the clean numbers.

**Lever 3 — precision override prompt (gated `ESTIMATE_PROMPT=precision`): NET LOSS.**
Targeted the observed over-read mechanisms (Q24 dump: reader over-SPLITS runs into
many identical 15" vanities — 8 vs 2 real — and DUPLICATES one 24×96 tall as both
tall+wall). Suffix appended to v4: fewest/widest cabinets, each physical unit once,
nothing mandatory, don't pad. Full clean ruler N=1, paired micro-avg on the 15
completed quotes: **baseline recall 35% / prec 30% / F1 0.324 → precision recall 30% /
prec 31% / F1 0.304.** It pruned pred 217→178: 3 real wins on over-readers (Q8 +0.20,
Q24 +0.14, Q6 +0.09) but 6 losses on under-readers (Q20 −0.20, Q5 −0.18, Q11/Q1/Q14/
Q23). A global precision bias robs the under-readers to pay the over-readers — the
corpus is split, so a blunt global nudge can't win. Kept gated/dormant (prod = v4;
the suffix is useful for a future PER-DOC adaptive path since it clearly helps
over-readers). Commit: (this session).

**PLATEAU CONFIRMED (rigorously, on the fixed ruler).** THREE global levers tested +
ruled out this session — stronger model (Opus 4.8), router merge-not-drop, precision
prompt — all wash/negative around **F1 ~0.30-0.32**. This is the zero-shot VLM ceiling
the research predicted ([[vlm-plan-counting-techniques]]), now PROVEN on real labeled
data rather than asserted. The strategic tension is real: fully-autonomous high accuracy
is fundamentally hard prompt-only, and the detector escape hatch is closed by the
no-labeling constraint.

**NEXT — only ADDITIVE levers remain** (gains without the recall↔precision tradeoff):
(1) **image path** (Q2/Q11/Q13 ~0 F1 — a dedicated upscale/OCR path adds F1 where it's
zero, hurting nothing else; SCR-005); (2) **size/identity matching** (Q21 48/49 & Q10
13/14 nail COUNT but F1 ~0.47 — improving which cabinets match lifts both R and P).
Firm any candidate at N=3. Global prompt/model tuning is done — do not re-litigate.
Still prompt/vision-only.

---

## 2026-07-01 (c) — H2: per-line labels + reading-accuracy scorer (the real ruler)

**Context:** Live testing exposed that the $-total backtest ("8/21 within ±10%")
was measuring LUCK — a read can price close while listing the wrong cabinets (the
Dean case). Pivoted to H2 (measurement) per the autonomous-target decision: build
per-line ground truth + a reading metric so drawing-reading is provable.

**What shipped (eval infrastructure — NO prod behavior change):**
- `apps/workers/scripts/extract-labels.mjs` → `labels.json`: parses the real
  CabinetNow quote PACKETS (the answer key in each folder) into per-line ground
  truth via the SAME shared `extractCabinetSchedule` (packets are CabinetNow's own
  R1C1 schedules). **17/21 quotes, 361 labeled cabinets** {tag, category, W, H, D,
  qty}. Gaps (deferred per owner): Q16/Q17 format variant, Q15/Q19 no packet.
- `@scribe/shared reading-score.ts` `scoreReading(predicted, labels)`: greedy
  unit-level match (same category + size within W±3"/H±6") → recall / precision /
  F1 / count-error / size-error. 6 unit tests.
- `apps/workers/scripts/score-reading.mjs`: runs the pipeline per drawing, scores
  vs labels, aggregates per quote + per document class. Harness `--json` now emits
  a `boxes` array.
- Experimental (GATED, off by default, NOT a prod change): `extractPage` accepts
  `opts.grounding`; harness `GROUND_READING=1` injects printed dims+labels into the
  prompt. A/B on the Cyncly Dean file: 14→11 boxes, +84%→+63% — modest; the residual
  is duplicate-elevation (same El on 2 pages), not sizing.

**FIRST READING BASELINE (17 quotes, N=1):** **recall 29% / precision 30% / F1 0.27**,
count-error 59%, size-error 1.7". Per class: labeled 0.35 (best) > sparse 0.31 >
image 0.17 ≈ arch 0.17 > image/sketch 0.09 (scan n=1 = 0.46). **Key insight:**
size-error is LOW (1.7") — when a cabinet is found it's sized fine; the failure is
COUNT/IDENTITY (recall+precision), i.e. a DETECTION problem, not prompt-tuning.
Q8 Piestewa (our all-session "$ −7% showcase") is only 36% recall / 25% precision —
the $-metric hid a mostly-wrong read. Scorecard: `~/Desktop/Scribe Testing/reading-scorecard.csv`.

**Code touched:** packages/shared/{reading-score.ts, index.ts, test/reading-score.test.ts};
apps/workers/scripts/{extract-labels.mjs, score-reading.mjs, estimate-floorplan.mjs};
apps/workers/src/takeoff/extract.ts (grounding hook). Build + tests green (shared 98 / workers 13 / pricing 44).

**Deploy/infra:** none — eval tooling only; `labels.json` + `reading-scorecard.csv`
live in `~/Desktop/Scribe Testing` (external, not committed). No Railway change.

**PRs:** this PR (H2 eval infra). #221 (router) + #224 (schedule) already merged/live.

**Open / next:** the ruler now enables the real decision — measure whether grounding /
duplicate-elevation collapse move F1 on `labeled`; the near-zero `arch`/`image` tail
is the quantified case to start the DETECTOR (H3), whose training labels ARE these
361 rows. Firm up with an N=3 median pass; close the 4 label gaps if wanted.

---

## 2026-07-01 (b) — text-layer schedule extractor (Class 1: input already lists the cabinets)

**Context:** Owner live-tested Q24 (Dean vanity). The uploaded input was a
CabinetNow **spec sheet whose text layer contains the actual cabinet schedule**
(`R1C1 Vanity Sink Base 15 34½ 24 …`), but the pipeline estimated from the
drawings — invented a trash pullout, wrong widths — and the $-total matched only
by luck (the sharpest possible argument for H2 per-line labels). Built the Class-1
extraction path: when the input already lists the cabinets, read them verbatim.

**Shipped (PR #221):**
- `pdf.ts` **`pageTextFragments`**: mupdf structured text → positioned {x,y,text}
  fragments (a flat dump collapses table columns; positions let us rebuild rows).
- `@scribe/shared` **`schedule.ts`**: `reconstructRows` (group fragments by y,
  order by x, join columns) + `extractCabinetSchedule` (parse each row → cabinet
  line; conservative gating: ≥3 rows with plausible cabinet dims + a casework
  noun, so dimension-annotated *drawings* don't mis-fire). `parseDimCell` handles
  `34 1/2`→34.5 etc. Lines are `estimated:false`, confidence 0.9 (schedule-grade).
- `process.ts` + harness: **before any vision**, try the text schedule; if found
  (≥3 rows) read it verbatim and **skip vision entirely** (0 tokens). Falls back
  to the router/estimator otherwise. Wired via the shared parser (no drift).

**Validated on the real Dean spec sheet:** 8 lines read exactly (5 vanity sink
bases 15/24/30/24/15, tall 24×96, 2 fillers) vs the invented 5; **LOW $5,626 vs
real $5,289 = +6.4%** (within ±10%), **0 vision tokens**. Reading is now *correct*,
not lucky. **Zero-regression:** the detector fires on NONE of the 21 backtest docs
(all drawings/images), so the benchmark is unchanged — no re-backtest needed.
Tests: shared 92 / workers 13 / pricing 44 green.

**Next:** this is the first slice of the input-type/document-class work. Still open:
SCR-007 yield-guard (elevation-authoritative under-reads), image path (SCR-005),
and H2 per-line labels (this extractor also produces clean label data).

---

## 2026-07-01 — page-role router shipped: over-read tail tamed (MAE 59→34), new under-read tail surfaced

**Context:** FIX phase for SCR-003 over-reads. Built the page-role router in
`process.ts` + shared, backtested the 21 quotes before/after, merged PR #221 to
prod for live testing. Branch `claude/elegant-hertz-3d705e`.

**Shipped (all on PR #221):**
- **`routeByPageRole` in `@scribe/shared`** (regions.ts): stop SUMMING cabinets
  across every relevant page. Pick ONE authoritative page role by precedence
  `schedule > floor_plan > elevation` (highest role with ≥1 real box wins — a
  ≥1-box fallback prevents a misclassified site plan zeroing the count), count
  from that role only, dedup within it (schedule → `dedupeLines`, plan/elevation
  → `collapseCrossViewDuplicates`). Demoted roles (elevations under a plan/
  schedule) no longer ADD to the count. `pageClassToRole` maps classes → roles.
- **`isNonBoxCasework` / `dropNonBoxCasework`**: fillers/crown/returns/toe-kick
  were priced through the full box-carcass formula (a 3" filler charged as a
  cabinet). Now dropped from box pricing + excluded from `boxFaceArea` consensus.
- **`withSocketRetry` in `lib/anthropic.ts`**: wraps all four vision calls
  (extract/classify/regions/spreadsheet) — retries `UND_ERR_SOCKET`/5xx with
  backoff so a dropped socket no longer fails a whole takeoff/quote.
- Router wired into BOTH `process.ts` and the harness via the shared helper (no
  drift). Unit tests: shared 84 / workers 13 / pricing 44, build green.

**Backtest (21 quotes, N=3, before→after):** **mean abs err 59.1% → 34.1%**
(within ±10%: 9 → 7). The catastrophic over-read tail is gone — Q19 ikea
+421%→+16%, Q14 +178%→+7%, Q21 +168%→−41%, Q24 +121%→+57%, Q7 +65%→+50%.

**NEW problem surfaced — under-detection (SCR-007):** the "drop ALL elevations in
Regime A" rule is too blunt. On docs where the floor plan is schematic and the
cabinet detail lives in the ELEVATIONS, dropping them throws away the count:
Q5 +19%→−80%, Q13 +6%→−42%, Q22 −1%→−66%, Q23 +13%→−50%, Q6 −9%→−24%. Q14 (4pg,
helped) and Q13 (4pg, hurt) are structurally identical — page count/type/size do
NOT separate them; only WHICH view is authoritative does.

**Decision + next (the data-driven plan, owner greenlit 2026-07-01):** treat plans
as distinct **document classes** by which view is authoritative, not by file shape:
1 itemized-list (IKEA/schedule — extract verbatim, Q19/21), 2 plan-authoritative
(count plan — Q14/24), 3 elevation-authoritative (count elevations — Q5/13/22/23),
4 single-view (Q7/16/20), 5 sparse image (Q2/11, SCR-005). Classes 2 vs 3 are
indistinguishable upfront → resolve by **completeness**: replace the router's fixed
precedence with a **box-face-area yield comparison** (only demote elevations when
the plan/schedule yield is comparable/larger). Next pass: confirm the yield feature
(1 read/page diagnostic), implement completeness-aware routing, re-backtest.

---

## 2026-06-30 — backtest harness, expanded to 21 quotes, over-read root-caused

**Context:** Continuation. Built a real backtest harness, owner added 14 more real
quotes (Quote 11-24), ran the expanded set, and diagnosed the dominant failure
(over-reading). No estimator fix shipped yet — this session is tooling + dataset +
diagnosis. Branch `claude/elegant-hertz-3d705e` (PR #221), NOT merged/deployed.

**What shipped (tooling, all on the branch):**
- `apps/workers/scripts/estimate-floorplan.mjs` refactored: estimate core is an
  importable `estimatePdf(input)` (PDF *or* image, converts images via `sips`) + a
  `--json` mode; CLI only runs when invoked directly. Added diagnostics to the human
  report: `boxes by source_page`, `boxes by room`, per-line `source_page`.
- **`apps/workers/scripts/backtest.mjs`** (new): reads a quotes manifest, runs each
  quote in its own process with bounded `--concurrency`, writes a CSV incrementally
  (LOW/MED/HIGH diffs + best tier + within-±10%) + a summary line. NO 10-min cap when
  run locally (that was only CC's background-shell sandbox). `backtest-quotes.example.json`
  committed; real manifests live in `~/Desktop/Scribe Testing/` (not committed).
- Bug fix: macOS screenshots name the space before AM/PM as **U+202F** (narrow
  no-break space); a regular space in the manifest won't match the file → renamed the
  Q17 file, and hardened `toPdfPath` to fail loudly (existsSync) instead of ENOENT.

**Dataset + scorecard:** test set 9 → **21 usable quotes** (excl Q4 out-of-scope, Q12
dup of Q3, Q18 empty). Manifest `~/Desktop/Scribe Testing/backtest-quotes.json`;
scorecard `~/Desktop/Scribe Testing/scorecard-21quotes.csv`. **v4+area = 8/21 within
±10% + 4 near-miss (~13-16%) = 12/21 within ~16%; mean abs err 44%.** within:
Q8/9/10/13/16/20/22/23. The 9-quote set under-represented OVER-reads — the big set
shows over-read is the dominant tail: Q19 +257%, Q21 +176% (277 boxes!), Q14 +169%,
Q24 +132%, Q7 +60%. Under-read on sparse/image inputs: Q2 −90%, Q11 −52%, Q15 −40%,
Q1 −26%. Clean mid-size designs reliably within.

**ROOT CAUSE of over-reads (confirmed via per-page/per-room diagnostics on Q14/Q24/Q19):**
an authoritative count source exists, then **elevation/millwork pages RE-ENUMERATE the
same cabinets**, and the dedup (`collapseCrossViewDuplicates` / `dedupeLines`) can't
merge them because the model's room/tag labels differ across views.
- Q14: floor plan = 19 (correct) + 3 elevations added 27 dupes → 46.
- Q24: one vanity run counted on 2 elevation pages (11+10) → 21 (+ fillers/molding
  over-emitted as priced boxes).
- Q19: schedule mode — schedule tables + 8 elevations dumped 52 boxes on "Kitchen 2".

**PLANNED FIX — page-role router (count each room ONCE):** route by which page-roles
the doc has; one authoritative count per room, priority `schedule > floor_plan > single
best elevation`; elevations REFINE sizes, never ADD to an established count.
A=plan present (Q14/21), B=elevations-only (Q24/7), C=schedule present (Q19),
D=single image/sketch (the separate under-read problem, Q2/Q11). Plus: retry on
transient API socket errors (`UND_ERR_SOCKET` failed whole quotes on big docs); don't
price fillers/crown/returns as boxes.

**PRs:** #221 (Steps 1+2 + area-consensus + this tooling). **Open:** build the
page-role router + re-backtest the 21; resolve Q22 ground truth (used sum of 14
sections = $92,276.58 — confirm vs Zoho); detector still the durable path.

---

## 2026-06-29 (c) — count≠price: area-aware consensus; v5 prompt tried + reverted

**Context:** Continuation. Researched how others do plan-reading takeoff (saved to
memory `[[vlm-plan-counting-techniques]]`): commercial tools (Togal/TakeoffBOT/
Exayard) use TRAINED object-DETECTION models, not zero-shot VLM; zero-shot
floor-plan counting tops ~0.39 acc / ~29.5% MAPE (AECV-Bench). Best zero-shot
levers: "point-label-count" (localize before counting), grid overlay (VISER),
self-consistency (= our median-of-N). Then tested the top lever.

**v5 prompt ("point, label, count"):** added per-cabinet LOCATION (in notes) +
systematic L→R scan + role-prime + a left→right verify pass, on top of v4's domain
rules. Backtested all 9 (consensus-3). Result: MIXED and net WORSE — it helped
borderline/under cases (Q3 −15%→−4%, Q5 +15%→+8%) but amplified the over-reader
(Q7 +33%→+88%) and worsened complex plans (Q6, Q1). The "4/9" it scored was a
±10%-boundary artifact; by mean-abs-error it was 35% vs v4's 27%. **Reverted to v4.**

**Key discovery — box COUNT is a weak proxy for the quote total; SIZE dominates.**
Q8 priced −6% vs −28% on two reads that BOTH had 20 boxes — the cabinets differed
in width/door-config/ft². So:
- **Consensus now selects by a quote-total proxy** (`boxFaceArea` = Σ width×height×qty
  over box lines, in `@scribe/shared`), NOT by line count. Shared `pickMedian` +
  `boxFaceArea`, used by both `process.ts` and the harness. Unit-tested (6 cases).
- **Use mean-abs-error, not "X/9 within ±10%", to compare configs** — with ~4 quotes
  parked near the ±10% line and real run-to-run noise, the binary count bounces ±1-2
  per pass and is untrustworthy for A/B.

**Four-config backtest (consensus-3, best tier vs real $):**
| config | mean abs err | solid ≤±10% |
|---|---|---|
| **v4 + area (SETTLED)** | **25%** | Q8 −4%, Q9 +7%, Q10 −4% |
| v4 + count | 27% | Q8/Q9/Q10 |
| v5 + count | 35% | (boundary 4/9) |
| v5 + area | 36% | Q8/Q9/Q10 |

Settled on **v4 prompt + area-aware consensus**: 25% mean, 3 solid + 3 near-misses
(Q3 −13%, Q5 +13%, Q6 −14%), 3 hard fails (Q7 +60% over-read, Q1 −26% multi-page
under, Q2 −90% image). area-consensus recovered Q8 (the v5 −28% was a v5 artifact).

**Conclusion — prompt+consensus has PLATEAUED (~25% mean / 3-of-9 solid), as the
research predicts for zero-shot.** The 3 near-misses are noise-limited at the
boundary; the 3 hard fails need per-bucket mechanisms (over-read pruning for Q7,
an image path for Q2) or — for real accuracy — a trained cabinet detector (label
the real quotes → YOLO; hybrid detector-counts + VLM-sizes). That's the strategic
fork to decide before more spend. Build + tests green (shared 71, workers 13).
NOT committed (owner asked to leave uncommitted); NOT deployed.

---

## 2026-06-29 (b) — port reading fixes to prod + median-of-N consensus (SCR-006)

**Context:** Continuation of the 2026-06-29 backtest. Goal: get the harness-proven
reading fixes into the REAL pipeline (`process.ts`) so prod == what was tested, then
tame the run-to-run variance (SCR-006) that was making tuning fight noise. Branch
`claude/elegant-hertz-3d705e` (merged in `scribe/estimate-reading-accuracy`; NOT
merged to main / deployed).

**Step 1 — ported the 3 harness-only fixes into `apps/workers/src/takeoff/process.ts`:**
- (a) **whole-page-once** for non-`floor_plan` estimate sheets (elevation/millwork):
  read the whole sheet once instead of per-region, so a kitchen drawn as plan +
  several wall elevations isn't re-enumerated per view.
- (b) **non-estimate cross-page dedup** (`dedupeLines` across all pages) for labeled
  (schedule) designs that repeat the same tagged cabinet on plan + elevation pages.
- (c) **universal face expansion** — `expandToComponents` now runs in BOTH modes
  (was estimation-only), so every quote mirrors a real CabinetNow packet.
- **De-duplicated the logic:** the cross-view collapse lived in BOTH the harness
  `.mjs` and `process.ts`. Extracted it to `@scribe/shared` as
  `collapseCrossViewDuplicates`; prod and the harness now import the SAME function,
  so the backtest can't drift from prod. Unit-tested (5 cases).

**Step 2 — SCR-006 variance (pipeline-side median-of-N):**
- New shared `pickMedian(items, count)` (unit-tested, 6 cases). `process.ts` and the
  harness each read every ESTIMATE page N times and keep the median-box-count read;
  env `ESTIMATE_CONSENSUS_N` (default **3**, set 1 to disable). Schedule reads stay
  single (already deterministic). Costs Nx vision tokens on the no-schedule path only.
- **Result:** Q8 Piestewa went **5/21/24 → 19/19/24** across three runs — the
  catastrophic 5-box under-read is gone; internal reads now cluster 19–26 so the
  median can't collapse. Variance tamed; a single consensus pass now reproduces what
  needed a manual median-of-3.

**Scorecard after Steps 1+2 (single consensus-3 pass, best tier vs real $):**
still **3/9 within ±10%** — Q8 (HIGH −6%), Q9 (LOW +4%), Q10 (MED +8%). Remaining
failures map to the planned buckets: under Q1 (−44%, 15 box), Q3 (−15%, 22), Q6
(−25%, 18); over Q5 (+15% LOW, 59), Q7 (+33% LOW, 39); image collapse Q2 (−91%, 2
box). Steps 1+2 bought prod-parity + stability, NOT accuracy — accuracy is Steps 3–5.
Q8 also exposed the residual is UNDER-READ bias (truth 24–29 types, model typically
reads ~19), which median correctly stabilizes but does not fix → Step 4.

**Build + tests:** green. `@scribe/shared` 65 tests (collapse + pickMedian added),
`@scribe/workers` 13.

**Next:** Step 3 over-readers (Q5/Q7), Step 4 under-readers (Q1/Q3/Q6 + Q8 bias),
Step 5 image inputs (Q2 + confirm scribe-web JPEG-as-PNG bug). Then ONE PR off main
with the before/after scorecard, deploy, spot-check live. See roadmap + SCR-003..006.

---

## 2026-06-29 — estimate reading-accuracy backtest vs 10 real CRM quotes

**Context:** Owner pulled 10 real CabinetNow deals from the Zoho CRM (Custom
Cabinetry pipeline) into `~/Desktop/Scribe Testing/Quote 1..10`, each folder with
an INPUT (plan/design/image) + the actual quote packet PDF. Goal: backtest the
no-schedule estimator end-to-end (input → estimate → tier price) against the real
quote totals, in a closed feedback loop, to drive most within ±10%.

**Harness, not deployed:** all runs used `apps/workers/scripts/estimate-floorplan.mjs`
(reads a PDF, runs the REAL classify/locate/extract modules + pricing). Needs
`ANTHROPIC_API_KEY` in `apps/workers/.env` (owner reused the prior key — still
**MA-011 rotate**). Images converted to PDF via `sips`. Ground-truth totals pulled
from each packet via `pdftotext` (older packets show `SUBTOTAL`, newer ones a
single `Total`; both = deal AMOUNT in Zoho, cross-checked).

**Infra built (in the test folder, reusable):** `run-parallel.sh` (all 9 at once,
~5 min, no Anthropic rate-limiting), `run-median.sh` / `run-r3.sh` (median-of-3),
`parse-median.sh` (median box count + tier totals + diff%). NOTE: a `run_in_background`
Bash job is killed at ~10 min wall — keep each background batch under that (one
parallel round of 9 ≈ 5 min is safe; 3 rounds must be split).

**Key findings (median-of-3, stable):** pricing is validated — the gap is READING
(box count), not pricing. 3/9 within ±10% on best tier (Q8 Piestewa HIGH −7%,
Q9 Maurer LOW +7%, Q10 Black Wind MED +8%). Failure buckets:
- **Over-read** (Q5 +48%, Q7 +53%): same kitchen enumerated once per view
  (plan + each elevation) and summed; Q7 also model over-enumeration (~37 types
  for one kitchen, run-splitting + island/elevation re-counts).
- **Under-read** (Q1 −38%, Q6 −33%, Q3 −25%): large multi-room / multi-page
  architectural sets — estimator finds far too few boxes.
- **Image inputs collapse** (Q2 −92%): a single low-detail render yields ~2 boxes.
- **Run-to-run variance is large even at temp 0** (Piestewa: 5/21/24 boxes across
  identical runs) — median-of-3 was needed just to get stable signal.

**Changes made (branch `scribe/estimate-reading-accuracy`, commit b861b69 —
EXPERIMENTAL, NOT merged/deployed):**
- `packages/prompts/src/estimate.ts` → **v4**: fillers sparing (was emitting ~11
  per kitchen), "count each cabinet once" across plan+elevations, per-room realism
  cap (~12–25 kitchen cabinets). Mixed result — helped over-readers, over-corrected
  some under (Q3 flipped).
- `apps/workers/src/takeoff/process.ts`: cross-view collapse in estimation mode
  (per normalized room, keep MAX count per tag across views). Weak alone (tags
  differ across views).
- `apps/workers/scripts/estimate-floorplan.mjs` (HARNESS ONLY): whole-page-once for
  elevation/millwork sheets (Q7 81→55 boxes), **non-estimate cross-page dedup**
  (Q9 50→25 boxes, +72%→+7% LOW — the biggest win), and universal door/front
  expansion. **These three are NOT in `process.ts` yet** — they must be ported to
  the real pipeline before any deploy.

**Decision:** do NOT merge/deploy yet. The fixes that moved the needle are
harness-only and prod ≠ what we tested; results are mixed (3/9). Bank the
diagnosis, port + validate next.

**Owner deliverable:** Google Sheet
(`docs.google.com/spreadsheets/d/1p-mtMjr2PuXCizPrIkA6Za9u7uSNQB6GFXTSS_53a9s`)
populated with Quote Total / Generated Total (median) / Price-difference-% formula
/ per-deal Analysis column.

**Open items → next session:** see roadmap "Estimate reading accuracy — close to
±10% on real quotes" + new bugs SCR-003..006.

---

## 2026-06-23 — session wrap-up: streaming fix validated; branch ready to merge

**Context:** Continuation session after context compaction. Branch
`scribe/fix-truncated-region-drop` (entries j + k + streaming) was pushed but
not yet merged. Session confirmed the fix, updated tracking docs, prepared for
merge.

**Validated live (harness run):** 45 line items, 23 boxes, kitchen present, no
errors. MEDIUM −7% / HIGH +7% vs $27,733.68 — both within 10%. The "Streaming
is required for operations that may take longer than 10 minutes" error is gone.

**Bookkeeping:** `roadmap.md` — "Doors-aware pricing" marked done (PR #216);
"No-schedule reading" updated to in-progress. History condensed: entries
2026-06-10 through 2026-06-18 (f) archived to `engineering-history-archive.md`.

**Next session focus:** consistency hardening — run-to-run variance remaining
at temperature 0, bath-vanity sizing flicker, ~6-box gap vs the real quote.

**PRs:** `scribe/fix-truncated-region-drop` — 3 commits (salvage parser +
temperature 0 + streaming). Merge → Railway auto-deploy → reprocess Piestewa
takeoff to confirm kitchen is stable in the live UI.

---

## 2026-06-18 (c) — crawl drawings only: SAM.gov active, permit datasets paused

**Context:** Owner wanted the prospector to use sources that actually carry
**drawings** (so the new detail view has plans to preview / send to takeoff),
keeping the permit sources but not running them. Researched the "PlanHub-style"
plan rooms (spike §C): PlanetBids is an undocumented JS SPA (probes returned the
app shell / 405), Bonfire + DemandStar require registration to download docs
(violates the public-data-only rule), and PlanHub/ConstructConnect/Dodge are
paid + ToS-prohibited. So no municipal plan room is cleanly crawlable today.
**Of the four seeded sources, SAM.gov is the only one that attaches public plan
PDFs** — the three Socrata sources are permit *signals* (`document_urls: []`).
Owner chose "SAM.gov only."

**What shipped (workers/db only — no API/web change):**
- **Paused the permit datasets:** SF/LA/NYC Socrata sources → `status=inactive`
  in `seed.ts` (fresh installs) + migration `0003_drawings_sources.sql`
  (already-seeded prod). Kept, not deleted — re-enableable from Admin → Crawler
  Sources. `runAllSources` only runs `active` sources.
- **SAM.gov kept active + tuned:** broadened casework keywords (added
  "architectural woodwork", "kitchen renovation"); migration mirrors it.
- **Fixed SAM.gov attachment download** (`run.ts` `authedDocUrl`): the resource
  links require the api_key, so it's appended **at fetch time only** for
  `*.sam.gov` hosts — the clean URL is what persists to
  `project_documents.fetched_from_url` and what gets logged, so the secret never
  lands in the DB or logs. Downloads stay PDF-only (zip bundles skipped — noted
  as a follow-up).
- **Seed INSERT now sets `status`** (was relying on the column default).

**Load-bearing:** **MA-008 (SAMGOV_API_KEY on `scribe-workers`) is now
load-bearing** — with the permit sources paused, SAM.gov is the only active
source, so without the key the Prospect Queue stays empty and no attachments
download. Updated MA-008, INSTALL §4, roadmap.

**Verified:** `pnpm build` 11/11, `pnpm test` 18/18, `pnpm eval` 100%. **Not
verified live** (no local SAM.gov key / Railway worker): after merge, set
`SAMGOV_API_KEY`, run the SAM.gov source from Admin, and confirm prospects with
downloaded plan PDFs appear in the detail view.

**PRs:** this PR (draft) — rides with the prospect-detail-view branch.

---

## 2026-06-18 (b) — C shipped: prospect detail view + send any plan to takeoff

**Context:** Task C (UI). The Prospect Queue only let you Triage/Ignore and (when
a doc was filename-classified `plan_set`) Run Takeoff — no way to open a
prospect, read its details, or see/preview the discovered drawings.

**What shipped (web-only — no API/DB/migration; all endpoints already existed):**
- **`View` button** on each Prospect Queue row → new route `/prospects/$projectId`.
- **`apps/web/src/pages/ProspectDetail.tsx`** (new): fetches `GET /projects/:id`
  and renders all project fields (address, jurisdiction, permit #, parcel, type,
  valuation, GC, score + rationale, description) plus the full **documents list**.
  Each doc shows its doc-class badge + page count, an **inline PDF preview**
  (presigned URL from `GET /project-documents/:id/url` in an iframe, fetched on
  demand + open-in-new-tab), and a **`Send to Takeoff`** button. Triage/Ignore
  mirrored in the header.
- **Send any document**, not only `plan_set` — `POST /takeoffs
  {project_document_id}` already accepts any doc, and the crawler's filename
  classifier (`run.ts` `classifyByFilename`) is rough, so a real plan can land as
  `other`. The queue's existing `plan_set`-gated Run Takeoff button is unchanged.
- **Source link** on the detail page: renders the prospect's `sourceRefs[].url`
  (the crawl origin — Socrata/SAM.gov listing) as external links, labelled by
  `external_id`.

**Verified:** `pnpm build` 11/11, `pnpm test` 18/18, `pnpm eval` 100%. **Not yet
verified live** — the presigned-URL iframe preview + takeoff-from-prospect only
fully exercise on Railway (no local API/MinIO). Confirm on deployed `scribe-web`
after merge: open a prospect with a discovered doc, preview it, send to takeoff.

**PRs:** this PR (draft).

---


## 2026-06-18 (k) — pin temperature 0 on takeoff vision calls (reproducible reads)

**Context:** Reprocessing the same plan gave a DIFFERENT cabinet list each run.
None of the worker vision calls set `temperature`, so they ran at the API
default 1.0 — both extraction AND the `locateRooms` region split resample every
time, compounding the drift.

**Shipped:** `temperature: 0` on the four takeoff calls — extract.ts (extract/
estimate), regions.ts (locate rooms/regions), classify.ts (page class),
spreadsheet.ts (header inference). Reads are now near-deterministic for a given
plan. (Vision isn't bit-identical even at temp 0, but variance drops sharply.)
Crawler `score.ts` left as-is (not in the takeoff path).

**PRs:** branch `scribe/fix-truncated-region-drop` (with (j)).

---

## 2026-06-18 (j) — fix silent whole-region drop on truncated extraction

**Context:** A deployed (v3) takeoff returned ONLY the bathroom + laundry
cabinets — the entire New Kitchen was missing. Cause: `extractPage` sends the
cabinet-dense kitchen crop, the model's JSON response exceeds `max_tokens`
(16000) and is truncated; `extractJson` does a hard `JSON.parse` → throws;
`readRelevantPage` catches it and `continue`s, dropping the whole region (only a
warning, easily missed). Kitchen is always the biggest region → always the one
that truncates → reproduces on every reprocess. Smaller rooms parse fine.

**Shipped (apps/workers extract.ts):**
- `salvageLineObjects(text)` — string-aware brace scanner that recovers every
  complete `{...}` from the `"lines"` array when the top-level parse fails
  (truncation only loses the last, incomplete cabinet). Used as a fallback when
  parse throws or yields zero lines, so a region is never silently emptied.
- Raised `max_tokens` 16000 → **32000** (billed only for tokens used) to avoid
  truncation in the first place. At that ceiling the SDK refuses a non-streaming
  request ("Streaming is required for operations that may take longer than 10
  minutes"), so the extract call now uses `messages.stream(...).finalMessage()`
  — same Message shape, same per-token cost. Re-validated live after the switch:
  no error, kitchen present, 23 boxes, MEDIUM −7% / HIGH +7% (within 10%).
- Surface a visible "response truncated (max_tokens) — verify" uncertainty when
  `stop_reason === max_tokens`, so a partial read is never silent again.

Tests: workers 13 pass incl. 3 new salvage cases (truncated mid-array; braces
inside strings; no-array). The earlier verbose `[ESTIMATED] …` notes inflate
output length and were the practical trigger.

**PRs:** branch `scribe/fix-truncated-region-drop`.

---

## 2026-06-18 (i) — estimate prompt v3: corners, specialty bases, fillers, vanity sizing

**Context:** Comparing our reprocessed takeoff to the real Piestewa quote
(pages 27-28) showed the reading under-detects: ~17 boxes vs the quote's 29. It
missed corners (Easy-Reach / Blind), specialty bases (Oven/Trash/Microwave),
fillers + end panels, Base Full-Height fridge surrounds, deep/wide wall runs;
rounded odd widths to standard; undersized the double-sink vanity (read 36" vs
77"); and invented Island/Bev-Fridge/Optional-Wall units not on the plan.

**Shipped:** `@scribe/prompts` estimate prompt → **v3** (`estimate-v3`):
- CORNERS MANDATORY — one corner cabinet at every inside corner where runs meet
  (Easy-Reach Corner Base/Wall, or Blind Corner when runs are unequal).
- Explicit specialty bases listed individually: Oven Base, Trash Pullout Base,
  Microwave Over Drawer Base.
- Fillers (1-3") + End Panels (~1.5") to make runs sum — emitted as
  casework_base with "Filler"/"End Panel" in the tag so expand.ts skips
  faces (no phantom doors) but they still box-price.
- Fridge surround modelled as Base Full-Height end panels + deep wall/bridge.
- Vanity sized to the FULL run; double-sink = one wide 4-drawer unit, not 36".
- Keep the odd width a run requires (37.25", 49.375"); don't force round numbers.
- Don't INVENT cabinets that aren't drawn (no "optional"/"beverage fridge").

Tests: shared 54 pass incl. new filler/end-panel & "cubbies" → no-faces coverage.

**Validated live** (estimate-floorplan.mjs on the 2440 E Piestewa plan):
box count **25 units / 24 types** (was ~17; quote = 29/24), and full tier
pricing **MEDIUM $27,721 = −0%** vs the $27,733.68 subtotal (LOW −11%, HIGH
+14%). v3 now emits the corners (Easy-Reach Corner Base/Wall), Oven Base, fridge
full-height surround panels, and run-sized vanities (38.5/30/27) it used to
miss. Follow-on fix: expand.ts no-faces regex now also catches "cubbies"
(plural) + appliance/range slots (was spawning ~$360 of phantom doors on the
open CUBBIES unit). Residual: still a few boxes short of 29 (no Trash Base /
Blind Corner / multi Base-Full-Height — partly plan-specific), and a "Range
Base" appliance-slot is still emitted as a box.

**PRs:** branch `scribe/drawer-box-hardware`.

---

## 2026-06-18 (h) — branded quote PDF + tier-priced itemized list

**Context:** The "Generate PDF" output was barebones — rows OVERLAPPED (a
long Tag wrapped but the row only advanced one line, so the next row crashed
into it), no branding, and it showed the OLD product-line subtotal ($10,962)
instead of the tier estimate the web UI shows.

**Shipped:**
- Rewrote `apps/api/src/lib/quote-pdf.ts`: per-row height = max cell height
  (`heightOfString`) so nothing overlaps; CabinetNow maroon header/title band +
  quote meta; room-grouped rows (subheaders) with zebra striping; right-aligned
  money; totals box; tier label. Verified with a render preview.
- New `priceQuoteLineItems(lines, tier)` in `@scribe/pricing` (single source of
  truth): prices each read line for the tier (boxes per unit, doors/fronts by
  ft²) + ONE rolled-up hardware row; items sum to subtotal. Exported
  `TIER_BOX_SPECIES`.
- `POST /quotes/:id/pdf?tier=` now prices via the tier model (was product-line
  `run`); web passes the selected tier. PDF + web now show the same number.

**Confirmed against the real quote (pages 27-28):** CabinetNow's quote IS three
lists — Doors/Fronts, CABINET BOXES (incl. a Toe Kick Skin line), DRAWER BOXES &
HARDWARE (Dovetail boxes + Blum 563H glide kits ×9 + Bulk Shelf Pins ×3) —
SUBTOTAL $27,733.68 − 10% = $24,960.31. Exactly the reverse-engineered model.

**Open (reading, next):** extraction under-detects/mis-sizes vs the real 29-box
list — misses corners (Easy Reach / Blind Corner), specialty bases (Oven/Trash/
Microwave), fillers/end-panels/toe-kick, Base Full Height, Deep Wall, big wall
runs; rounds widths (37.25→36, 49.375→40, 77→36) and undersizes the double-sink
vanity; invents Island/Bev-Fridge/Optional-Wall. Glides/pins/toe-kick still
unpriced. Persist tier server-side (currently query param, default medium).

**PRs:** branch `scribe/drawer-box-hardware`.

---

## 2026-06-18 (g) — drawer-box hardware: CabinetNow's 3rd list (one rolled-up line)

**Context:** The tier estimate priced only CabinetNow's first two lists (doors/
fronts by ft², cabinet boxes per unit). The third list — drawer boxes + hardware
— was missing, so the estimate ran ~9% light.

**Shipped:** ported the live store's `pricing.js` `drawerBoxes()` formula into
`@scribe/pricing` `hardware.ts` (per box: perimeter = 2·W+2·D; a tier line
`slope·perimeter+intercept` picked by drawer-front HEIGHT; then
`((tier×materialMult)+$10.06)×1.5`). `priceHardware(lines)` makes **one dovetail
drawer box per `drawer_front` face** (the expand step already emits those) and
sums to a **single rolled-up "Hardware" subtotal** (not a line per piece, per
owner). Wired into `priceQuoteTiers` as a constant across tiers (drawer-box
species isn't the rep's door-style choice — matches how CabinetNow's lists #2/#3
stay flat). QuoteBuilder shows boxes + doors/fronts + hardware in the breakdown
and Totals. Back-test on the Piestewa quote: 18 boxes add ~$2,387, LOW now
**+3%** vs $27,733.68 (was −5% without hardware).

**Open:** glides, shelf pins & toe-kick skin are option SKUs (not formulas in
pricing.js) — still not modelled, but they're the small remainder. The live
under-count (~20 vs ~29 boxes, reading completeness) still applies.

**PRs:** branch `scribe/drawer-box-hardware`.

---

---

## 2026-06-18 (f) — unify quote Totals with the tier estimate (web)

**Context:** The Quote Builder showed two disagreeing numbers — the new
"Estimated Price (boxes + doors)" tier card vs. the old "Totals" card (still
driven by the placeholder product-line run).

**Shipped:** QuoteBuilder Totals now uses the **selected tier** as its subtotal
(`quote_tiers[tier].total_cents`), with markup/handling/freight applied on top;
the admin margin note matches. Picking a tier in the estimate card updates the
Total. The product-line `run` is kept only for freight + the lead-time /
needs-review banners. Web-only, no API change.

**Open:** retire the placeholder "Priced lines (pricing config v1)" panel
entirely; persist the chosen tier server-side. Separately, the live estimate
reads low vs the quote because the takeoff detected ~20 boxes vs the quote's
~29 (reading completeness, not pricing).

**PRs:** this PR (branch `scribe/unify-quote-totals`).

---

## 2026-06-18 (e) — cabinet-box pricing + Shaker-anchored door tiers → within 10%

**Context:** Closing the gap to the real CabinetNow quote ($27,733.68 subtotal).
Owner supplied the store's `pricing.js` (box pricing source) and confirmed two
live prices that calibrated everything.

**Shipped (`@scribe/pricing`):**
- **`boxes.ts`** — port of `pricing.js` `cabinetBoxes()`: per-family (base/wall/
  tall/vanity) carcass surface-area + face-frame rail model × species rail rates
  × the ×5 "cnowservice" markup (+$100 oversize). **Validated: a 36×34×24 Red
  Oak base = $732.65 vs the live site's $734.83 (0.3%).** Cheapest species =
  Poplar; material only swings a box ~12% (carcass/shelf are flat).
- **`tiers.ts` reworked** — door/front $/ft² now **anchored on real Shaker 3/4
  rates from Airtable** (Shaker = most common + cheapest; base = paint-grade
  $22.74 door / $33.10 front). Confirmed the Airtable "Price" IS the real $/ft²
  (a 15×30 Aries Natural-Birch door = $111.78 = $35.77/ft² exactly). Pricier
  tiers are ESTIMATED multipliers (×1.6 / ×2.5) with a `DOOR_TIER_DISCLAIMER`.
- **`quote-tiers.ts`** `priceQuoteTiers` — combines boxes (per-tier species) +
  door/front faces into one low/mid/high total. `GET /quotes/:id` returns
  `quote_tiers`; QuoteBuilder shows an "Estimated Price (boxes + doors)" card
  with a selectable tier + disclaimer.

**Result (quote's actual items through the combined pricer):** LOW $26,239
(−5%), MEDIUM $29,746 (+7%), HIGH $33,884 (+22%). The real Aries/Pecan quote
sits between LOW and MEDIUM — **both within 10% of $27,733.** Target hit.

**Still open:** drawer boxes + Blum glides + shelf pins + toe-kick (the quote's
3rd list, small $); tall/corner box geometry is approximated (base validated,
talls looser); persist the chosen tier into the quote total; the old product-
line "Priced lines" panel still shows placeholder NEEDS-REVIEW alongside the new
tier card.

**Verified:** `pnpm build` 11/11, `pnpm test` (pricing 36), `pnpm eval` 100%.

**PRs:** this PR (branch `scribe/cabinet-box-pricing`).

---

## 2026-06-18 (d) — door/front tier pricing (low/mid/high $/ft²)

**Context:** With cabinets expanding into door/front faces (2026-06-18 (c)), price
those faces. Owner decision: bake the tiers (don't ping Airtable per quote) and
offer low/mid/high for the rep to pick.

**Shipped:** `@scribe/pricing/tiers.ts` — baked `DOOR_TIERS` ($/ft² for door +
drawer-front, low/mid/high = catalog p25/p50/p90 from
`scripts/airtable-pricing-explore.mjs`: doors $45/$57/$84, fronts $45/$51/$75) +
`priceFacesByTier(lines)` (pure, 4 tests) summing door/front ft² × tier rate.
Doors-only (boxes excluded). Harness wired to print the 3 tier totals.

**Validated end-to-end on the Piestewa plan (read → expand → price):** 148 ft²
doors + 22 ft² fronts → LOW $7,700 / MED $9,603 / HIGH $14,106. Quote was
Aries/Pecan (premium) so HIGH ≈ $14.1k is the analog; doors are ~half the
$27,733 subtotal (boxes still needed for the full total).

**Wired into the app:** `GET /quotes/:id` now returns `door_tiers`
(`priceFacesByTier` over the takeoff lines; `priceFacesByTier` accepts a minimal
`FaceLike` so the API's DbLine maps in). QuoteBuilder shows a **"Door & Drawer
Pricing"** card — Low/Med/High selectable buttons with each tier's total, labeled
"doors + drawer fronts only — boxes not yet priced." Selection is local state
(not persisted; no migration). The existing product-line Totals card is
unchanged (still placeholder/NEEDS-REVIEW for boxes).

**Verified:** `pnpm build` 11/11 (incl. web), `pnpm test` (+4; pricing 30),
`pnpm eval` 100%.

**Open items:** persist the chosen tier + fold it into the quote total once the
**cabinet-box price source** lands (the other ~half of the subtotal).

**PRs:** this PR (branch `scribe/door-tier-pricing`).

---

## 2026-06-18 (c) — box→door/front expansion (estimate line items)

**Context:** Live review of the no-schedule estimate showed only cabinet boxes;
the owner's CabinetNow quote has cabinet boxes PLUS a separate door & drawer-front
list (doors priced by ft²). Those faces are derived from the boxes, not read off
the plan.

**Shipped:** `expandToComponents` in `@scribe/shared` (pure, 8 tests) — given a
cabinet's category + width + height + door/drawer config (parsed from the
estimator's notes, with standard fallbacks: sink base→2 doors, *-drawers→3
fronts, surrounds/panels/cubbies→none), it generates the door (`door`) and
drawer-front (`drawer_front`) face line items at standard sizes (wall = full
height; base/tall/vanity less a 4.5" toe-kick; stacked drawers short). Wired into
`process.ts`: in estimation mode each cabinet spawns its faces, appended to the
takeoff lines. Local harness now emits ~22 boxes + ~43 door/front pieces (quote
has ~52). Faces are `estimated` + low-confidence and currently match no product
line (priced once the Airtable ft² tiers land — next).

**Verified:** `pnpm build` 11/11, `pnpm test` (+8; shared 53), `pnpm eval` 100%.
Validated live via the local harness (real model).

**PRs:** this PR (branch `scribe/cabinet-door-expansion`).

---

## 2026-06-18 (b) — reading overhaul (no-schedule estimation) + pricing groundwork

**Context:** Validated the no-schedule estimator (B) end-to-end against a real
CabinetNow quote ("MidMod - Piestawa Peak", subtotal $27,733.68) + its floor
plan (2440 Piestewa). Goal: get the estimated line items to roughly match the
quote's ~24 cabinets, as the precursor to hitting the price within 10%.

**Pricing model learned (not built yet):** a CabinetNow quote = 3 priced lists
(doors/fronts by **ft² × style × material**, cabinet **boxes** per unit, drawer
boxes/hardware) − a **flat 10% discount**. Door/front $/ft² lives in **Airtable**
(`Material Master 2021`, base `appBoHee0bMpXB0WK`; `Price = Base×Mult+Tackons`).
Percentile tiers ($/ft²): doors $45/$57/$84, fronts $45/$51/$75 (low/mid/high).
Doors-only back-test: doors are ~30–54% of the subtotal → **boxes are the other
~half** (box price source still TBD). The current `packages/pricing` prices ONE
blended `framed-casework` line per cabinet — no door/box decomposition — so it
can't reproduce a CabinetNow total yet. See memory + `scribe/scripts/`.

**Reading shipped (workers/shared/prompts; merged-to-main pending PR):**
- **Lenient line parse** (`extract.ts`): one malformed line (qty 0 / stray gap
  marker) no longer throws away the whole page/region.
- **Estimate prompt v2**: lay out the run like an estimator — enumerate EVERY
  cabinet, place specials at sink/range/DW/fridge/corner, add uppers + tall
  pantries, tag each with type + door/drawer config, stay in scope.
- **Per-room segmentation** (`LOCATE_ROOMS` + `locateRooms`): split a whole-house
  floor plan into per-room crops so each room is laid out coherently; floor plans
  use room segmentation, sheets use drawing segmentation.
- **Lenient region parse** (`parsePageRegionsLenient`, +`PageRegion`): a malformed
  box no longer discards the locate result.
- **Estimation reads each region as one image** (no fragmenting a room).
- Local harness `apps/workers/scripts/estimate-floorplan.mjs` runs the real
  modules on a PDF (needs `ANTHROPIC_API_KEY`). Result on Piestewa: 6 vague
  generic boxes → **24 tagged cabinets** w/ config, kitchen enumerated by wall.

**Verified:** `pnpm build` 11/11, `pnpm test` (+region-parse tests; shared 45),
`pnpm eval` 100%. Reading validated live via the local harness (real model).

**Open items:** bath-vanity consistency (77" master double flickers — model
variance); doors-aware pricing (Airtable tiers + box→door/front decomposition);
cabinet-box price source. **Security:** an Anthropic API key was shared in chat
this session for local runs — rotate it.

**PRs:** this PR (branch `scribe/reading-cabinet-schedule`).

---

## 2026-06-18 — B shipped: estimates for plans with no cabinet schedule

**Context:** Task B — produce cabinet estimates when a set has no schedule.
Grounded in the owner's **Highland Model B** set: its only cabinet signal is the
**floor plan** (kitchen run + island, 5 bath vanities, closets); the pages
labelled "ELEVATIONS" are *exterior* elevations, and the rest are 3D views. So
floor-plan estimation is the core — the research-doc assumption that no-schedule
sets still have interior elevations to box-count didn't hold.

**What shipped (workers/shared/prompts only — no API change, no migration):**
- **Estimation mode** (`process.ts`): when classification finds no
  `cabinet_schedule_table`, the pipeline also reads `floor_plan` pages (ignored
  before) and runs in estimate mode; a doc-summary banner records "no schedule
  found — quantities ESTIMATED, verify before quoting."
- **`ESTIMATE_SYSTEM` prompt** (`@scribe/prompts/estimate.ts`): infers cabinetry
  from a floor plan / interior elevation (kitchen base+wall runs less appliance
  gaps, islands, vanities, closets) using printed dims + drawing scale, emits
  standard-size boxes summing to each run; explicitly ignores exterior
  elevations / 3D / site plans (returns empty). Same `PageExtraction` shape →
  reuses the repair/match/review path.
- **`markEstimated`** (`@scribe/shared/estimate.ts`, unit-tested): sets
  `estimated: true` (new `CabinetLineItem` field, default false), caps confidence
  ≤ 0.5 (below the 0.8 review threshold), prefixes `[ESTIMATED]` to notes.
  Builds on §A: a large floor plan's kitchen comes back as one legible `plan`
  region, so estimation reasons over a whole drawing, not blind tiles.
- **No DB column / API gate** (owner "warn-only"): the flag rides the note prefix
  (CSV export derives `estimated` from it) + low confidence; `eval_fixtures`
  capture `estimated` in their JSON. Send safety leans on the existing low-conf
  review + the `needs_review`/unpriced send gates.

**Verified:** `pnpm build` 11/11, `pnpm test` (+5 estimate tests), `pnpm eval`
100% (fixtures back-compat via the field default). **Not yet verified with a live
model** (no local key) — confirm on deployed `scribe-workers` by uploading
Highland / the Piestewa floor plan and checking the Review screen for low-conf
`[ESTIMATED]` lines. Single-image (non-PDF) uploads stay normal-extract for now.

**Follow-ups:** LF→$ ROM pricing; optional hard estimated-line send-gate.

**PRs:** #204 (merged 2026-06-18). Owner confirmed estimates work live on real
plan sets (Highland / Piestewa) 2026-06-18 — the "not yet model-verified" caveat
is closed.

---

## 2026-06-17 (b) — A shipped: legible large-format reads (region-crop + tiling)

**Context:** Followed the research spike (below) by building task A. Root cause:
the extractor sent one full-page render to `claude-sonnet-4-6`, which downscales
anything past 1568px long edge / ~1568 visual tokens, so a 36×24" sheet's
schedule text collapsed to ~4px. Validated on the owner's real sheets — cropping
a single elevation to native res makes the same content fully legible.

**What shipped (workers-only; no migration, no new env var):**
- **`@scribe/shared/regions.ts`** (pure, 18 unit tests): vision-budget math
  (`fitDpi`, `needsRegioning`), `planRenderJobs` (fit a rect in one image or an
  overlapping grid that respects the 1568px edge + 1568-token budget),
  `mapBoxToPagePoints` / `padRectToPage`, `dedupeLines`, `PageRegions` zod.
  Constants default to Sonnet's limits so an Opus high-res knob drops in later.
- **`@scribe/prompts/regions.ts`**: `LOCATE_REGIONS_SYSTEM` + version; plus
  `extractRegionUserText` (tells the model it's seeing a crop, not the page).
- **`apps/workers/src/takeoff/pdf.ts`**: `renderRegion` (mupdf
  `Pixmap`+`DrawDevice`+`page.run` clip render — validated against poppler) and
  `pageDimsPt`.
- **`takeoff/regions.ts`** `locateRegions` (best-effort vision segmentation) +
  **`process.ts`** `readRelevantPage`: small pages keep the single-image path;
  large sheets → locate drawings → crop+extract each at full res → dedupe within
  a region. Detection/extraction failures fall back to whole-page tiling + warn.
  Per-takeoff token budget still guards cost (large page ≈ 1 locate + 6–12 crop
  extractions vs 1 before).

**Verified:** `pnpm build` 11/11, `pnpm test` (+18), `pnpm eval` 100% (eval reads
stored fixtures, unaffected). mupdf clip render confirmed to produce the
legible elevation crop.

**PRs:** #203 (merged 2026-06-17). Owner confirmed large-format reads work live
2026-06-18.

---

## 2026-06-17 — research spike: plan-reading + PlanHub-style discovery (A/B/C)

**Context:** Owner asked for three improvements — (A) read small/illegible text
on large plans, (B) estimate from plans with no cabinet schedule, (C) a
PlanHub-style crawler for cabinet plan deals. Session was scoped as
**research-only** (no production code); deliverable is a decision doc.

**Key finding (A):** the extractor sends one full-page render at a fixed 200 DPI
to `claude-sonnet-4-6`, whose native vision resolution is **1568 px long edge**.
A 34×44" E-sheet at 200 DPI (6800×8800) is downscaled to ~1211×1568 before the
model sees it, so schedule text (~25px) lands at ~4px — illegible. Raising DPI
doesn't help (gets downscaled harder); the fix is **crop the schedule region /
tile the page** so each region is rendered at ≤ the model's native resolution
(≈1:1). Opus 4.8/Fable 5 raise the limit to 2576px (high-res vision) but a full
E-sheet still downscales ~0.29×, so a model swap alone is insufficient.

**Findings (B):** no-schedule plan sets yield ~0 lines today; industry practice
is box-count off elevations + linear-foot runs off the floor plan. Recommend
elevation extraction with an `estimated` flag + a gated LF ROM estimate (never
to a `sent` quote). Depends on A.

**Findings (C):** PlanHub/ConstructConnect/Dodge/BidClerk are gated, paid,
ToS-prohibited — do NOT scrape. The defensible "PlanHub-style" path is a new
adapter (behind the existing `fetchSince` interface) for **public** e-procurement
plan rooms (Bonfire/BidNet/DemandStar/PlanetBids/OpenGov) that publish drawings,
+ casework-relevance scoring in `score.ts` → one-click Run Takeoff.

**Validated against 4 real owner-supplied sets** (not committed — client PII):
a 36×24" Arch-D kitchen sheet, a 36×24" floor plan, a letter-size kitchen
design (plan + ELV callouts), and Highland Model B (A1 3D export, floor-plan
only). Crop test proved §A: the kitchen elevation is illegible squashed to
1568px but fully legible cropped at native res. **Key new finding: none of the
four has a tabular cabinet schedule** — cabinet data lives in dimensioned
elevations + plan callouts, so "schedule-first" is the wrong default for
residential. §B splits into B1 (elevations exist → box count) and B2
(floor-plan-only like Highland → scale-aware LF). Vector-text fast path (§A4)
viable for 3 of 4; Highland's fonts aren't embedded (`uni: no`) so it needs
vision. Details in the spike doc's validation section.

**Deliverable:** `scribe/research/plan-reading-and-crawler-spike.md` (full
analysis, options, recommendations, LOE, validation, sources). Roadmap seeded
with three new backlog items (§A pri 8, §B/§C pri 6). No pipeline code changed.

**PRs:** this PR (docs only, draft).

---

## 2026-06-16 (b) — SCR-002: CORS blocked every SPA mutation (PUT/PATCH/DELETE)

**Context:** The newly-shipped admin "AI Cross Validation" toggle did nothing
when clicked (no error). Reproduced live in the owner's browser: clicking
fired only the `OPTIONS` preflight (204) with no `PUT` following.

**Root cause:** `@fastify/cors` in `apps/api/src/app.ts` was registered with
only `origin`/`credentials` — no explicit `methods`. The deployed
`Access-Control-Allow-Methods` was `GET,HEAD,POST`, so the cross-site browser
(web and api on different `*.up.railway.app` subdomains) refused to send any
`PUT`/`PATCH`/`DELETE`. Latent since first deploy — no mutation had been
exercised in prod yet; it affected ALL saves (org-settings, pricing, line
PATCH/DELETE, templates, sources), not just the toggle.

**Fix:** explicit `methods: [GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS]` on
the cors registration. Deployed via `scribe-api` redeploy; owner confirmed the
toggle (and saves generally) now persist.

**Code touched:** `apps/api/src/app.ts`, `bugs.md`.

**PRs:** #201 (merged + deployed 2026-06-16).

---

## 2026-06-16 — AI cross-validation toggle (secondary OpenAI extraction)

**Context:** Owner wanted a way to sanity-check the Anthropic extraction with
a second model. Requirement: a toggle named "AI Cross Validation" in admin;
Anthropic ALWAYS runs, and when the toggle is on the same page images also go
to OpenAI through the same steps/output shape.

**Design decisions (confirmed with owner):** results surface by *lowering the
primary line's confidence on disagreement* (not a side-by-side UI); cross-val
runs on the **extract** stage only (not classify); OpenAI model `gpt-4.1`
(`OPENAI_VISION_MODEL` override). Anthropic stays the source of truth — OpenAI
lines are never injected, only used to flag.

**What shipped:**
- **DB:** migration `0002_cross_validation.sql` + Drizzle mirror —
  `org_settings.cross_validation_enabled bool default false`.
- **Comparator:** pure IO-free `applyCrossValidation(primary, secondary)` in
  `@scribe/shared` (tag/category match w/ 0.51" dim tolerance, one-to-one;
  disagreement → conf ≤0.6 + note; primary-only → conf ≤0.7 + note;
  secondary-only → flag, never injected) + 7 unit tests.
- **Workers:** `lib/openai.ts` (lazy client, `openaiConfigured`,
  `OPENAI_VISION_MODEL` default `gpt-4.1`); `takeoff/cross-validate.ts`
  (same `EXTRACT_SYSTEM` + image via OpenAI chat-completions vision,
  `response_format: json_object`, zod-validated, nomenclature-repaired);
  `process.ts` reads the flag, threads it through the PDF + image paths,
  best-effort per page (failures warn, never fail the takeoff), stores OpenAI
  raw + token count in `doc_summary.cross_validation`. OpenAI tokens are NOT
  counted against the Anthropic per-takeoff budget (different pricing).
- **API/Web:** `PUT /admin/org-settings` accepts `cross_validation_enabled`
  (GET already returns the row); "AI Cross Validation" checkbox added to
  Admin → Branding & Freight.
- **Docs:** `.env.example` (`OPENAI_API_KEY`, `OPENAI_VISION_MODEL`),
  `INSTALL.md` (§1 table, workers env, §4 limits), `manual-actions.md`
  MA-010 (set the key on workers — optional; toggle is a no-op without it).

**Verified:** `pnpm build` (11/11), `pnpm test` (incl. 7 new cross-validation
tests), `pnpm eval` green. Confirmed live in prod 2026-06-16 (key set per
MA-010, toggle exercised on a real takeoff) — note SCR-002 (CORS) had to be
fixed first before the toggle could be saved.

**Code touched:** `packages/db/migrations/0002_cross_validation.sql`,
`packages/db/src/schema.ts`, `packages/shared/src/cross-validation.ts` (+test,
+index export), `apps/workers/src/lib/openai.ts`,
`apps/workers/src/takeoff/cross-validate.ts`,
`apps/workers/src/takeoff/process.ts`, `apps/workers/package.json` (openai dep),
`apps/api/src/routes/admin.ts`, `apps/web/src/pages/Admin.tsx`, `.env.example`,
`INSTALL.md`, roadmap/manual-actions.

**Open items:** none — `OPENAI_API_KEY` set and toggle confirmed working
(MA-010 completed 2026-06-16).

**PRs:** this PR (draft).

---

## 2026-06-12 (b) — first production deploy completed (owner + session)

**Context:** Owner worked through the first-deploy bootstrap with this
session walking him through it (no local checkout — everything via the
Railway/Google/MinIO UIs plus PRs #194/#196/#197).

**What happened:** Railway project live (api/web/workers + Postgres + Redis
+ MinIO w/ volume + shared `R2_*` vars + bucket `scribe`); Google OAuth
client created (first attempt registered the bare domain →
`redirect_uri_mismatch`; fixed to the full `/auth/google/callback` path);
boot migrate+seed ran on the #196 deploy; #197 bearer-token session deployed
and the new web bundle verified live. External checks green: `/health`,
`/health/db`, OAuth redirect, CORS. MA-001…MA-005 moved to Completed;
MA-009 added (MinIO lifecycle rule — console build lacked the setting).

**Open items:** owner login confirmation (closes SCR-001), real pricing
rates (MA-006), Socrata field-map validation (MA-007), SAM.gov key (MA-008),
MinIO lifecycle via `mc` (MA-009), first real plan-set extraction +
re-baseline evals (top roadmap item).

**PRs:** #194, #196, #197 (all merged); this wrap-up PR (docs only).

---

## 2026-06-12 — SCR-001: cross-site session (login loop on Railway domains)

**Context:** First prod login looped back to the sign-in screen. Web and api
run on different `*.up.railway.app` subdomains; `up.railway.app` is on the
Public Suffix List → cross-site, so browsers refuse the API's SameSite=Lax
session cookie on the SPA's fetches and `/auth/me` 401s.

**What shipped:** bearer-token session path alongside the cookie. OAuth
callback redirects to `${WEB_PUBLIC_URL}/#session=<token>`; the SPA captures
the fragment into localStorage before render (and strips it from the URL) and
sends `Authorization: Bearer` on all API calls. The API accepts the token
from header or cookie. Cookie path still works (top-level navigations like
the CSV-export links send Lax cookies, and a future same-site custom-domain
setup makes it primary again).

**Code touched:** `apps/api/src/auth.ts`, `apps/api/src/routes/auth.ts`,
`apps/web/src/api.ts`, `apps/web/src/main.tsx`, `bugs.md`.

**PRs:** #197 — bearer-token session fix (merged 2026-06-12; deployed and verified live).

---

## 2026-06-10 (c) — boot-time migrate + seed (no local tooling for deploys)

**Context:** Owner has no local checkout/toolchain; the manual migrate+seed
step (old MA-005) was the only part of first-deploy that required one.

**What shipped:** `apps/api/src/server.ts` runs `migrate()` + `seed()` before
listening — pg advisory lock (727501) serializes replicas, failure is fatal
in production (failed deploy > half-migrated app) and a warning otherwise,
`SKIP_BOOT_MIGRATIONS=1` opts out. `@scribe/db` now exports `migrate`/`seed`.
`INSTALL.md` and MA-005 rewritten: new migrations apply automatically on the
deploy that ships them; seed reads `AUTH_ALLOWED_EMAILS` from the api env.

**Code touched:** `apps/api/src/server.ts`, `packages/db/src/index.ts`,
`INSTALL.md`, `manual-actions.md`.

**PRs:** #196 — boot-time migrate + seed (merged 2026-06-12).

---

## 2026-06-10 (b) — object storage: all-on-Railway via MinIO

**Context:** Owner has no Cloudflare account; everything must run on
Railway. The storage package was already endpoint-generic S3.

**What shipped:** `packages/storage` now defaults to path-style addressing
(`forcePathStyle`, opt-out `S3_FORCE_PATH_STYLE=0`) so MinIO works without
wildcard DNS, plus an `R2_REGION` knob; `.env.example`, `INSTALL.md` §2, and
`manual-actions.md` MA-001/MA-003 rewritten for a MinIO service + volume in
the Railway project (public domain on the S3 API port so presigned URLs are
browser-reachable; 90-day `prospect-docs/` lifecycle via `mc ilm`). R2/S3
remain drop-in alternatives. Env var names keep the `R2_*` prefix to avoid
churn — they're generic S3 settings.

**Code touched:** `packages/storage/src/index.ts`, `.env.example`,
`INSTALL.md`, `manual-actions.md`.

**Deploy/infra state touched:** none yet (first deploy still pending).

**PRs:** #194 — MinIO/path-style storage (merged 2026-06-10).

---

## 2026-06-10 — v1 framework: full scaffold through first-deploy readiness

**Context:** Project start. PRD v1.2 (`PRD.md`) is the source of truth; the
owner compressed the 8-week timeline to 48 hours for a first deployable
build. Conventions mirrored from sauce.ai/signal (engineering-flow docs,
Railway deploy, scoped CI, merge=union tracking docs).

**What shipped (single PR):**

- **Monorepo scaffold** (pnpm workspaces + Turborepo, TS strict, Node 22):
  apps `api`/`workers`/`web`, packages `shared`/`pricing`/`freight`/
  `export`/`prompts`/`db`/`storage`, plus `evals/`.
- **packages/shared:** zod schemas for the whole domain (CabinetLineItem,
  PageExtraction, PricingSnapshot, ShipmentSpec, ExportTemplate, …);
  deterministic nomenclature parser (`parseTag`: W/B/SB/DB/BC/T/TP/U/V
  families, 2/4/6-digit dims, default depths per PRD §6.3) and
  `repairLine` post-parser (fills dims from tags, flags tag/width
  disagreements by lowering confidence instead of overwriting).
- **packages/pricing:** pure engine — `priceLine` (rate × size measure +
  finish/assembly adders, flat or %, integer cents) and `priceQuote`
  (markup/handling/freight, max/mixed lead times, needs_review propagation);
  `matchLine` (category + fuzzy material/finish resolution + dim-bounds →
  match_confidence + ≤3 alternates; no-match → unmatched bucket reason);
  seed product lines with all rates `needs_review: true`.
- **packages/freight:** `FreightProvider` interface; `FlatPalletProvider`
  (volumetric pallet heuristic, 40%/75% efficiencies, round up, min 1);
  `UberFreightProvider` stub that throws; `freightVerificationRequired`
  (≥ $35k or assembled casework).
- **packages/export:** template-driven CSV (escaping, mm conversion, Y/N
  booleans, literal columns); default Mozaik/KCD/generic templates.
- **packages/db:** hand-written `0001_init.sql` (all PRD §5.5/§6.6 tables +
  users, eval_fixtures, export_templates, token_spend), Drizzle schema
  mirror, idempotent migrate runner (tracked in `_migrations`), idempotent
  seed (product lines, pricing config v1, templates, org settings, Wave-1
  sources SF/LA/NYC + SAM.gov, allowed users from `AUTH_ALLOWED_EMAILS`).
- **apps/api (Fastify):** Google OAuth (manual fetch flow, no-self-signup
  allow-list, HMAC-signed cookie sessions, dev-bypass) + role guards;
  takeoff upload (multipart → R2 → BullMQ) and from-prospect-doc; line
  PATCH/DELETE; approve gate (snapshots approved lines into eval_fixtures);
  CSV export by template; quotes (create from approved takeoff, re-price
  against the PINNED pricing config, send gates: freight-verified +
  no-NEEDS-REVIEW + no-unpriced), verify-freight, pdfkit quote PDF (logo +
  terms from org settings) to R2 with signed URL; projects queue endpoints;
  admin (pricing editor PUT → new immutable version, test calculator against
  draft config, org settings + logo upload, export-template editor, sources
  CRUD + run-now, users); dashboard aggregates (quotes by status, weekly
  quoted/won, turnaround, freight est-vs-actual).
- **apps/workers (BullMQ):** takeoff pipeline — R2 fetch → mupdf
  rasterization (50 DPI thumbnails / 200 DPI extraction) → Sonnet
  (`claude-sonnet-4-6`) batched thumbnail classification (~8 pages/call;
  ~25 calls per 200-page set, within the PRD's <40 target without the
  sheet-index shortcut) → per-relevant-page extraction (schedules first) →
  zod validation + nomenclature repair → single-unambiguous-multiplier
  application (everything else flags, never assumes) → product-line matching
  → takeoff_lines + page PNGs to R2 for provenance + pre-correction
  eval_fixture; spreadsheet intake (SheetJS, deterministic header synonyms,
  Haiku-assisted mapping fallback, fraction parsing); image intake;
  per-takeoff token budget (hard cap → status failed) and daily crawler
  budget (token_spend). Crawler — config-driven generic Socrata adapter +
  SAM.gov adapter behind a common `fetchSince(cursor)` interface; polite
  fetch (1 req/sec/host, honest UA with contact email, 429/5xx backoff);
  heuristic scoring (negative/positive signals, $3,500/unit and 4%-of-
  valuation scope estimates) + Haiku refinement within budget; dedupe by
  permit+jurisdiction then address (merges source_refs); plan-discovery
  (PDF download → R2 `prospect-docs/`, sha256 dedupe, filename doc-class);
  6-hour repeatable scheduler + per-source run-now.
- **apps/web (React/TanStack/Tailwind):** login gate (Google) + role-aware
  nav; Prospect Queue (above/below the $35k fold, Run Takeoff one-click,
  triage/ignore); Takeoffs (upload, auto-refresh while processing); Takeoff
  Review (split view source-page image ↔ lines, ↑/↓/e/enter keyboard flow,
  inline edit, low-confidence highlight, batch-accept, unmatched bucket with
  product-line picker, approve → Build Quote); Quote Builder (priced lines
  with lead times, markup/handling/freight-override fields, mandatory
  freight-verified checkbox, NEEDS-REVIEW and split-shipment banners, PDF
  generation, mailto send draft from hank@cabinetnow.com); Dashboard; Admin
  (pricing editor + live test calculator, branding/terms/freight settings,
  CSV mapping editor, crawler sources health + run-now, user management).
- **evals/**: metrics (tag/category line matching with 0.5" dim tolerance →
  recall/precision/qty/dim accuracy, weighted aggregate), runner with
  >2-point regression gate vs `baseline.json`, synthetic
  `sample-residential` fixture (placeholder — see Load-bearing state).
- **Deploy/CI:** per-app Dockerfiles (multi-stage, `pnpm deploy --legacy`)
  + railway.json; `.github/workflows/scribe-ci.yml` (install/build/test/
  eval, path-scoped to `scribe/**`); `.gitattributes` merge=union rows for
  scribe tracking docs.

**Verified:** `pnpm build` (11/11), `pnpm test` (70 tests across 8 suites),
`pnpm eval` green; migrate+seed against a throwaway Postgres 16; API booted
against real DB — dev auth, seeded product lines, test calculator
($280/LF B24 maple painted assembled ×2 = $1,680 ✓), dashboard; `pnpm
deploy --legacy` bundle runs standalone with migrations included; mupdf
WASM loads under Node 22.

**Deliberate v1 cuts (tracked in `roadmap.md`):** OCR fallback, sheet-index
shortcut, per-line source-region highlight (full-page image instead),
BigCommerce draft orders (501 stub), bull-board/Sentry, agenda adapter +
remaining Wave-1 metros, eval-fixture export job, mailto-based send (no
attachment), dimension-increment enforcement.

**Code touched:** everything under `scribe/`, plus `.github/workflows/
scribe-ci.yml` and `.gitattributes` at the repo root.

**Deploy/infra state touched:** none (nothing deployed; bootstrap queued in
`manual-actions.md`).

**PRs:** #192 — v1 framework (merged 2026-06-10).

**Open items:** first Railway deploy (MA-001…MA-005), real pricing rates
(MA-006), Socrata field-map validation (MA-007), extraction validation on
real plan sets + re-baseline evals.
