# sauce.ai/scribe — engineering history

Chronological working history. Most-recent entries in full; older entries get
condensed into `engineering-history-archive.md` once this file approaches its
single-`Read` budget (~34 KB). The "Load-bearing state" and "PRD reference"
sections below are durable — never archive them.

---

## Load-bearing state (not in the repo — read first)

State that lives outside the repo and will reintroduce fixed bugs / break
deploys if a future session doesn't know it exists. Keep this current.

- **Deployed 2026-06-12 (Railway project, all services live):**
  - `scribe-api` → https://scribe-api-production-757c.up.railway.app
  - `scribe-web` → https://scribe-web-production.up.railway.app
  - `scribe-workers` (no domain), Railway **Postgres** + **Redis** plugins.
  - **MinIO** template service + volume; bucket `scribe`; S3 API exposed on
    the port-9000 public domain. Storage creds live as **project shared
    variables** (`R2_*`) referenced by api + workers. The 90-day
    `prospect-docs/` lifecycle rule is NOT configured yet (MA-009 — the
    console build lacked the setting; use `mc ilm`).
- **Schema is managed by api boot** (since #196): migrate + seed run before
  listen, advisory-locked, fail-fast in production. Never hand-apply
  migrations to prod; ship a migration file and deploy. `SKIP_BOOT_MIGRATIONS=1`
  opts out.
- **Google OAuth client** `241721814755-upo5…apps.googleusercontent.com` with
  redirect URI `https://scribe-api-production-757c.up.railway.app/auth/google/callback`
  (must be the full path — bare domain causes `redirect_uri_mismatch`).
  `AUTH_ALLOWED_EMAILS` on the api service seeds users; first email = admin
  (mhittle@gmail.com).
- **web and api are CROSS-SITE** (`up.railway.app` is on the Public Suffix
  List), so the SameSite=Lax cookie is never sent on SPA fetches. The
  **bearer-token session** (#197: callback `#session=` fragment →
  localStorage → `Authorization: Bearer`) is the load-bearing auth path —
  don't remove it unless web+api move to one registrable custom domain. The
  cookie still backs top-level navigations (CSV export links).
- **Dev-bypass auth:** with `GOOGLE_CLIENT_ID` unset and
  `NODE_ENV != production`, every API request authenticates as a local admin
  (`dev@scribe.local`). Prod has both set correctly.
- **Railway build shape:** each service's root directory is `scribe` (the
  monorepo root is the Docker context); config-as-code lives at
  `scribe/apps/<svc>/railway.json`. The web image bakes `VITE_API_URL` at
  BUILD time — changing the API domain requires a web rebuild.
- **Runtime images use `pnpm --filter <pkg> --prod deploy --legacy /out`** —
  verified standalone in the sandbox and now by real Railway builds (all
  three Dockerfiles build and run in prod).
- **Seeded pricing rates are placeholders** (`needs_review: true`); the API
  blocks `sent` quotes that price against them. Seeded Socrata field maps
  (SF/LA/NYC dataset ids + columns) are best-effort and must be validated on
  first pull (MA-007).
- **SAM.gov is the only active crawler source** (since 2026-06-18 (c), migration
  `0003`). The three Socrata permit datasets are seeded/migrated `inactive` (no
  drawings); SAM.gov attaches public plan PDFs. So `SAMGOV_API_KEY` on
  `scribe-workers` (MA-008) is **load-bearing** — without it the Prospect Queue
  is empty. Re-enable a permit source from Admin if permit signals are wanted.
- **The eval baseline (`evals/baseline.json`) is synthetic** (placeholder
  fixture at 100%/100%). Replace fixtures with real labeled plan sets before
  trusting the regression gate.
- **BullMQ bundles its own ioredis** — adding a direct `ioredis` dep breaks
  typechecking. Pass connection options (host/port/password parsed from
  `REDIS_URL`), not a Redis instance.
- **pnpm postinstall allow-list:** root `package.json`
  `pnpm.onlyBuiltDependencies` must include `esbuild` and `msgpackr-extract`
  or vite/bullmq silently get no native bits.
- **`packages/db` copies `migrations/` into `dist/` at build** — the migrate
  runner resolves SQL files relative to its compiled location; a build step
  change that drops the copy breaks `pnpm db:migrate` in prod images.
- **Stacked PRs: delete the base branch on merge, or the stack never reaches
  main.** 2026-09-13: #255/#256/#257 were each based on the PR below them;
  GitHub only retargets a stacked PR to `main` when its base branch is
  DELETED, so each one merged into the feature branch below it and `main`
  got PR 1 only while all four showed "merged". Fixed by #260 (the PR 3
  branch, which contained all the merges, opened against `main`). Either
  base every PR on `main`, or merge bottom-up and delete each branch.
- **`ROUTER_TOLERANT_MERGE=1` is SET on `scribe-workers`** (owner, 2026-08-12)
  — the demoted-role re-admit merge is LIVE prod behavior (kit-measured 0.379
  vs 0.328 baseline). Removing the var reverts to the plan-only router and
  silently re-breaks elevation-heavy docs. `ROUTER_ELEVATION_PRIMARY` exists
  gated but is NOT set (measured ≈ equal; don't set without new evidence).

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

## 2026-09-15 (d) — measuring answer unparseable → every size defaulted; salvage + retry + re-measure

**Owner's live job (MOLLY_CHARLEY, 24 cabinets on 3 elevation areas):**
Build ran ~2 min, then every cabinet came back 30" wide at 50% — the
review's notes said "measurements response was not parseable JSON — sizes
defaulted". The measure call had `max_tokens: 16000`, no `stop_reason`
check and no salvage; the page-reading path has had 32k + salvage since
June. Whether this answer was cut off or malformed is in
`takeoffs/{id}/beta/measure/response-0.txt` (not pulled).

**Fixed.**
- `max_tokens: 32000` on the measure call; `stop_reason === "max_tokens"`
  is logged and surfaces as a note ("cut off at the token limit; N of M
  cabinets salvaged").
- `parseMeasureResponse` salvages every COMPLETE cabinet object from an
  unparseable answer (`salvageArrayObjects(text, "cabinets")`, the same
  string-aware brace scanner as `salvageLineObjects`); note says how many.
- An answer with zero usable cabinets gets ONE fresh model call; still
  zero → the build throws ("the measuring step returned no usable sizes
  twice — click Build again"), rolls back (2026-09-15 (c)), and the
  wizard shows the error — instead of silently producing a takeoff of
  defaults that LOOKS finished.
- `POST /takeoffs/:id/remeasure` (review or awaiting_boxes): clears
  `built_at` on every scanned area, keeps the found cabinets, queues a
  build — "Measure again…" in the review's More menu (confirms; edits on
  those cabinets are replaced). This is the recovery for the live job.

**Gotchas.** (1) Each measuring attempt persists as `response-{attempt}.txt`.
(2) Re-measure re-prices only the rebuilt lines like any area build; hand-
drawn review lines (no area) are untouched. (3) The user's proposal
("read the printed dimensions near each box across every page") is what
the measure pass already does — `nearbyDims` per marker from the whole
page's text layer + every page sent as context; the failure was purely
the answer format.

---

## 2026-09-15 (c) — build failed in prod: `= ANY($list)` bug; builds now roll back and report progress

**Owner report (live, MOLLY_CHARLEY_KITCHEN):** Find found 8 cabinets;
Build errored `delete from takeoff_lines where … raw_model_output->>'parent'
= ANY(($2, $3, …))`. Root cause: PR 2's scoped deletes used
`sql\`… = ANY(${ids})\`` — drizzle expands a JS array into a parameter
LIST, so Postgres got `ANY((…,…))`, which is invalid (ANY wants an array).
It failed at the scoped pricing step, AFTER the lines had been inserted and
`built_at` stamped: the area read "in takeoff" with 8 unpriced lines and
Build then had "nothing new to build".

**Fixed.**
- All three sites (`replaceLinesForDetections`, scoped `priceAndExpand`,
  API `deleteLinesForDetection`) use `inArray(sql\`…->>'parent'\`, ids)`
  → `IN ($2, $3, …)`.
- `buildFromDetections` stamps `built_at` only AFTER pricing succeeds; on
  any failure after insert it deletes the inserted lines (+ faces) and
  clears `built_at`, so the areas read as scanned-but-unbuilt and Build is
  simply clickable again.
- `build-takeoff` self-repairs the state this bug left behind: an area
  stamped built whose lines were never priced (`product_line_id IS NULL AND
  unmatched_reason IS NULL` on every line) is reset to unbuilt.
- Progress during a build: the API writes `{stage: "measure", "Queued for
  measuring"}` when Build is clicked; the worker writes "Measuring N
  cabinets" before the model call; pricing writes "price". The Reading card
  picks its title and stage list from the real stage (Preparing your pages /
  Building your takeoff / Reading your drawings) instead of a client flag —
  the "went back to Preparing" confusion.
- `beta_build` jobs get `attempts: 2` (30 s fixed backoff) so a worker
  restart mid-build (a deploy) recovers on its own.

**Second live symptom, same day:** a job sat 25 min in `processing` showing
the stale hand-off line — consistent with the PR 1/PR 2 deploys restarting
the workers mid-build (unverified without the Railway log). The retry +
progress changes cover it; if it recurs, the worker log for that job is the
evidence to pull.

**Gotcha.** Never write `= ANY(${jsArray})` in drizzle `sql` — use
`inArray()`. Grep `= ANY(` in a review.

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

## Condensed history

### 2026-09-10 → 2026-09-13 (b) — Stage 1 UI rework, PRs 1–4 (archived verbatim)
Product pivot agreed (product-plan.md, #253). PR 1 design system (tokens via
`@theme inline`, `components/ui/`, `labels.ts`, shell Jobs/Quotes/Admin); PR 2
Jobs list + `takeoffs.progress` (migration 0009) + ReadingProgress + quotes
named by file; PR 3 Pages step + Review rework (60/40, rooms, inline product
picker, batch accept); PR 4 Quote step (tiers, gated Send, Done) + Admin port.
Stacked PRs #254–#257 never reached main until #260 (see Load-bearing state).
Full text in the archive.

### 2026-08-05 → 2026-08-18 — two-stage review → staged reads default → run decomposition (archived verbatim)
Zero-API read kits + step attribution (router role-drop was the top loss;
`ROUTER_TOLERANT_MERGE` 0.336→0.379). Two-stage human review (migration 0004,
prepare/extract/finalize jobs, bbox provenance), then the box gate removed
(review = interactive editor, faces keyed by `raw_model_output.parent`),
sideways-page normalization in pdf.ts, quote tier persisted (migration 0005).
Beta detect wizard (`takeoff_detections`, migrations 0006/0007) → staged reads
DEFAULT (#247; `STAGED_READS=0` reverts); fontconfig incident fixed by
fonts-dejavu-core in the workers image. measure-v6/detect-v5: plan runs
decompose into units via legible region crops (plan-kind kits 0.13→0.32, set
0.42→0.47), door swings excluded (SCR-010), review zoom/pan + dots. Full text
in the archive.

### 2026-06-18 (c)–2026-07-06 — reading-accuracy campaign (archived verbatim)
Prospect detail view (#218); drawings-only crawl (SAM.gov active, migration 0003).
CRM backtest vs 10→21 real quotes: pricing validated, READING is the gap; over-read
root-caused to cross-view re-enumeration. Median-of-N consensus (SCR-006), area-aware
pick, page-role router (over-read MAE 59→34; #226), text-layer schedule extractor
(Class 1), per-line reading ruler (scoreReadingDetailed, labels v1→v3), owner decision
H3: prompt/vision-only. Gated levers: ESTIMATE_PROMPT=precision, DIM_SKELETON
grounding, header-driven packet parsing. Full text in the archive.

### 2026-06-18 (g-k) — estimate pricing + reading hardening (archived verbatim)
Drawer-box hardware (3rd CabinetNow list, one rolled-up line); branded tier-priced quote PDF; estimate prompt v3 (mandatory corners, specialty bases, fillers/end-panels, run-sized vanities, no invented cabinets); salvage parser + 32k max_tokens + streaming to stop silent kitchen drop on truncation; temperature 0 pinned on all four vision calls. Full text in the archive.

### 2026-06-10 — v1 framework (PR #192) + MinIO storage (PR #194) + boot migrate (PR #196)
Full monorepo scaffold (pnpm/Turborepo, 3 apps, 8 packages); takeoff pipeline;
Mozaik/KCD export; Socrata+SAM.gov crawler; evals harness; Railway/Docker configs.
MinIO path-style storage via Railway service + volume; boot-time migrate+seed
(advisory lock, `SKIP_BOOT_MIGRATIONS=1` opt-out). **Server state:** all captured
in "Load-bearing state" above.

### 2026-06-12 — SCR-001: login loop (PR #197); first prod deploy
Bearer-token session (OAuth fragment → localStorage → Bearer header) to work around
cross-site Railway subdomains (SameSite=Lax cookie refused on SPA fetches).
Railway services live (api/web/workers + Postgres + Redis + MinIO); Google OAuth
client; boot migrate+seed confirmed on prod. MA-001…MA-005 completed.

### 2026-06-16 — AI cross-validation toggle; SCR-002: CORS fix (PR #201)
Cross-validation: `org_settings.cross_validation_enabled` (migration 0002); OpenAI
secondary extraction; confidence lowered on disagreement; MA-010 completed
(OPENAI_API_KEY set, toggle confirmed live). CORS: `@fastify/cors` was missing
PUT/PATCH/DELETE from `methods`; fixed in PR #201 — all SPA saves now work.
SCR-002 resolved.

### 2026-06-17 — research spike (§A/B/C); A shipped: region-crop + tiling (PR #203)
Spike confirmed Sonnet downscales past 1568px (E-sheet → ~4px text); no-schedule
residential sets need estimation; public plan rooms not cleanly crawlable.
**A shipped:** `@scribe/shared/regions.ts` (18 unit tests), `locateRegions`, mupdf
clip render, large-format legible-read path in `process.ts`. Confirmed live 2026-06-18.

### 2026-06-18 (early) — B shipped (PR #204) + pricing model (doors + boxes + unify)
Estimation mode + ESTIMATE_SYSTEM + markEstimated. Reading overhaul: v2 prompt,
per-room segmentation, lenient parse. Box→door/front expansion (expandToComponents,
8 tests). Door/front $/ft² tiers anchored on Shaker Airtable rates. Cabinet-box
pricing (port of pricing.js, 0.3% vs live item). Totals unified with selected tier.
Combined result on real items: LOW −5% / MEDIUM +7% vs $27,733.68 (within 10%).

---

## PRD reference

The full product spec is `scribe/PRD.md` (v1.2, June 2026 — final). Key
invariants enforced in code: integer-cents money; immutable pricing-config
versions pinned per quote; freight-verification gate (≥ $35k or assembled
casework); NEEDS-REVIEW rate send block; unmatched lines never dropped;
ambiguous unit counts flag rather than assume; per-takeoff and daily-crawler
token budgets; crawler politeness rules (1 req/sec/host, honest UA, public
data only).
