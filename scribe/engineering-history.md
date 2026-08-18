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
- **`ROUTER_TOLERANT_MERGE=1` is SET on `scribe-workers`** (owner, 2026-08-12)
  — the demoted-role re-admit merge is LIVE prod behavior (kit-measured 0.379
  vs 0.328 baseline). Removing the var reverts to the plan-only router and
  silently re-breaks elevation-heavy docs. `ROUTER_ELEVATION_PRIMARY` exists
  gated but is NOT set (measured ≈ equal; don't set without new evidence).

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

**Review UI: dots, not boxes** (owner: "bounding boxes are looking kindof bad").
`BoxOverlay` draws one category-colored DOT at each cabinet's centre; the
rectangle, its label and the resize handles appear on hover/selection, where
they are useful. Everything else is unchanged — click-to-select still syncs
with the line table, drag moves, corners resize, draw-new-box still draws. Dot
and handle sizes are computed from a ResizeObserver so they stay constant on
screen at any sheet resolution or panel width.

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

## Condensed history

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
