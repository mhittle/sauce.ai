# sauce.ai/scribe — roadmap

Backlog for the takeoff-to-quote pipeline + prospector, organized around the
PRD's milestones (§11; weeks 1–4 = revenue-critical quoting path). Each item:
Priority (1–10, higher = sooner), LOE (1–10, higher = more work), Category
(`infra`, `takeoff`, `pricing`, `crawler`, `ui`, `backend`, `algo`, `ops`,
`security`, `docs`).

Status values: `backlog` · `in-progress` · `done` · `blocked`.

---

## At a glance

| Title | Pri | LOE | Cat | Status |
|---|---|---|---|---|
| Staged reads (segment→boxes→detect→measure) as DEFAULT pipeline + beta detect wizard + zero-API kit harness | 9 | 8 | takeoff | done |
| Plan-only run→unit decomposition in the staged measure stage (staged ≈0.26 F1 on plans vs elevations ≈0.55) | 8 | 4 | takeoff | backlog |
| v1 framework — monorepo, takeoff pipeline, pricing, freight, quotes, UI, crawler, evals | 10 | 9 | infra | done |
| First Railway deploy (api/web/workers + PG + Redis + MinIO) | 10 | 4 | ops | done |
| Validate extraction on real plan sets + first real eval fixtures | 10 | 5 | takeoff | backlog |
| Legible large-format reads — region-crop + tiling (research: research/plan-reading-and-crawler-spike.md §A) | 8 | 6 | takeoff | done |
| Estimate from plans with no cabinet schedule — floor-plan/elevation estimation (research: spike §B) | 6 | 6 | takeoff | done |
| Public-plan-room crawler adapter + casework relevance scoring (PlanHub-style discovery; research: spike §C) | 6 | 6 | crawler | backlog |
| Crawl drawings only — pause permit datasets, make SAM.gov the active source + fix attachment download | 6 | 2 | crawler | done |
| AI cross-validation toggle (secondary OpenAI extraction → lower confidence on disagreement) | 6 | 4 | takeoff | done |
| Real pricing rates entered (clear NEEDS REVIEW) | 10 | 1 | pricing | backlog |
| Doors-aware pricing — Airtable $/ft² tiers + box→door/front decomposition (match CabinetNow quotes ±10%) | 9 | 7 | pricing | done |
| No-schedule reading: consistency hardening + tighter kitchen recall | 6 | 3 | takeoff | in-progress |
| Estimate reading accuracy — most real CRM quotes within ±10% | 9 | 8 | takeoff | in-progress |
| Decompose + DIM_SKELETON prompt A/B on fresh reads (~$5 API, owner go-ahead) | 8 | 3 | takeoff | backlog |
| Deterministic read checks — width-sum vs printed run, bbox overlap/aspect/coverage | 7 | 4 | takeoff | backlog |
| Room-keyed cross-view reconciliation (island/tower double-count class) | 7 | 6 | takeoff | backlog |
| End-panel handling — stop pricing 1.5" panels as full cabinets | 7 | 3 | pricing | backlog |
| Collect numbered-unit ground-truth packets (Wantoch-style) for the test set | 8 | 2 | algo | backlog |
| Validate seed Socrata field maps on first pull | 8 | 2 | crawler | backlog |
| Quote email drafting w/ PDF attached (replace mailto) | 7 | 3 | backend | backlog |
| OCR fallback for scan-only PDFs (tesseract) | 7 | 5 | takeoff | backlog |
| Sheet-index classification shortcut | 6 | 4 | takeoff | backlog |
| Prospect detail view — open project details + preview/send any discovered plan to takeoff | 6 | 2 | ui | done |
| 2-step human review — page-picker gate + interactive box review on the approve screen | 8 | 7 | ui | done |
| Review screen: click line → source region highlight | 6 | 5 | ui | done |
| Eval fixture export job (eval_fixtures → evals/plansets) | 6 | 2 | algo | backlog |
| Remaining Wave-1 permit adapters (San Diego, San Jose, Sacramento, Miami-Dade, Orlando, Tampa, Jacksonville) | 6 | 3 | crawler | backlog |
| Agenda-packet / state procurement adapter (≥5 adapters target) | 5 | 6 | crawler | backlog |
| Plan-discovery first-page vision check | 5 | 3 | crawler | backlog |
| bull-board behind admin auth + Sentry | 5 | 3 | ops | backlog |
| BigCommerce draft orders (parametric product mapping) | 4 | 6 | backend | backlog |
| Dimension increments enforcement + per-line dim-bounds editor UI | 4 | 3 | pricing | backlog |
| Multi-unit/commercial extraction hardening | 5 | 6 | takeoff | backlog |
| Pallet-heuristic tuning from logged actuals | 3 | 3 | algo | backlog |
| Uber Freight provider (v1.1) | 3 | 5 | backend | backlog |
| Outreach email drafting in Prospect Queue (v1.1) | 2 | 4 | backend | backlog |
| FL NOC + contractor-license adapters (v1.1) | 2 | 6 | crawler | backlog |

---

## Items in detail

### Staged reads as DEFAULT pipeline + beta detect wizard + zero-API kit harness

- **Status: done** (PRs #240, #242–#247, 2026-08-13→17). Segment
  (locateRegions/Rooms) → auto-seed `takeoff_detections` → per-region detect
  (count/label/box, no dims) → ONE whole-input set-of-marks measurements pass
  (per-marker proximity dim grounding, measure-v5) → replaceLines +
  priceAndExpand. Default since #247; `STAGED_READS=0` reverts to classic.
  Human wizard (`/takeoffs/:id/detect`) shares the same tables/jobs, so auto
  runs are inspectable/correctable. Zero-API harness: `prepare-staged.mjs` /
  `replay-staged.mjs`; 18-quote run: mean F1 0.42 vs 0.32 classic
  (elevations ≈0.55, plans ≈0.26) — kits in
  `~/Desktop/Scribe Testing/staged-kits/`.

### Plan-only run→unit decomposition in the staged measure stage

- **Priority 8 / LOE 4 / takeoff / backlog.** Staged v1 emits plan-view
  counter RUNS as single boxes; gold counts manufactured units — the whole
  staged-vs-classic gap on plan/sketch inputs (≈0.26 vs elevations ≈0.55).
  Port the classic decompose behavior (ESTIMATE_DECOMPOSE_SUFFIX spirit) into
  the measure stage for plan-kind regions: split runs into standard-width
  units at measure time, keyed off the run's printed length. Re-run the
  staged kits on the plan-only quotes (2, 6, 8, 1, 23) to verify before any
  further default changes.

### v1 framework — monorepo, takeoff pipeline, pricing, freight, quotes, UI, crawler, evals
**Priority/LOE/Category/Status:** 10 / 9 / infra / done (PR: this PR, 2026-06-10)
Everything in `engineering-history.md` 2026-06-10: pnpm/Turborepo scaffold,
schema + migrations + seed, PDF/XLSX/CSV/image takeoff pipeline, nomenclature
parser, pure pricing engine + matcher, flat-pallet freight + verification
gate, quote builder + PDF + send gates, Mozaik/KCD CSV export + mapping
editor, admin screens, Socrata + SAM.gov crawler with scoring/dedupe/
plan-discovery, eval harness, Railway/Docker configs, CI.

### First Railway deploy
**Priority/LOE/Category/Status:** 10 / 4 / ops / done (PRs #194/#196/#197 +
owner actions, 2026-06-12)
All services live on Railway (api/web/workers + Postgres + Redis + MinIO);
boot migrate+seed; bearer-token session for the cross-site Railway domains.
MA-001…MA-005 completed; MA-006…MA-009 remain open in `manual-actions.md`.

### Validate extraction on real plan sets + first real eval fixtures
**Priority/LOE/Category/Status:** 10 / 5 / takeoff / backlog
The pipeline is built but unvalidated on live documents. Run 3–5 public plan
sets (bid boards), review outputs, hand-label gold lines, replace the
synthetic `evals/plansets/sample-residential` fixture, re-baseline
`evals/baseline.json`. PRD targets: ≥95% recall, ≥97% qty/dim accuracy,
50-page set < 10 min.

### Legible large-format reads — region-crop + tiling
**Priority/LOE/Category/Status:** 8 / 6 / takeoff / done (#203, 2026-06-17; verified live 2026-06-18)
Root cause confirmed: Sonnet 4.6 downscales any image past 1568px long edge, so
a full E-size sheet rendered at 200 DPI (6800×8800) is squashed to ~1211×1568
and schedule text becomes ~4px tall. **Shipped:** large-format relevant pages
are segmented by a vision "locate" call into their distinct drawings; each
drawing is cropped (mupdf clip render) and re-rendered at full resolution, with
drawings too big for one image tiled and de-duplicated within the drawing.
Pages that already fit legibly (≤ letter-ish) keep the single-image path. Pure
planning/dedup math lives in `@scribe/shared regions.ts` (unit-tested);
`apps/workers/src/takeoff/{pdf,regions,process}.ts` do the rendering + model
calls. Best-effort: detection/extraction failures fall back to whole-page
tiling and warn. Follow-ups still open: Opus-4.8 high-res model knob, and the
vector-text fast path (§A4). Full analysis in the spike §A.

### Estimate from plans with no cabinet schedule
**Priority/LOE/Category/Status:** 6 / 6 / takeoff / done (#204, 2026-06-18; verified live 2026-06-18)
**Shipped:** when classification finds no `cabinet_schedule_table`, the pipeline
enters estimation mode — it also reads `floor_plan` pages (ignored before) and
runs a dedicated `ESTIMATE_SYSTEM` prompt that infers cabinetry from floor
plans/interior elevations (kitchen base+wall runs, islands, vanities, closets)
using printed dims/scale, emitting standard-size boxes that sum to each run.
Every estimation line is flagged `estimated` + capped to low confidence +
`[ESTIMATED]`-prefixed note (`markEstimated` in `@scribe/shared`), so it surfaces
in the Review screen's existing low-confidence highlighting and never reads as a
schedule-grade quantity; a doc-summary banner says no schedule was found. Builds
on §A region-crop (the kitchen comes back as one legible `plan` region).
**Warn-only** per owner decision 2026-06-17 — no API/send-gate change, no
migration (the flag rides the note prefix; `eval_fixtures` capture it in JSON).
Grounded in the Highland Model B set (floor-plan-only, no schedule). Follow-ups:
LF→$ ROM pricing, and a hard estimated-line send-gate if wanted. See spike §B.

### Public-plan-room crawler adapter + casework relevance scoring
**Priority/LOE/Category/Status:** 6 / 6 / crawler / backlog
"PlanHub-style" discovery done the defensible way: crawl public e-procurement
plan rooms (Bonfire/BidNet/DemandStar/PlanetBids/OpenGov etc.) that publish
solicitations with downloadable drawings — NOT the gated PlanHub/ConstructConnect/
Dodge networks (login-walled, paid, ToS-prohibited; need a paid/partner feed,
an owner decision). New adapter behind the existing `fetchSince` interface +
casework-relevance scoring in `score.ts` → one-click Run Takeoff. See spike §C.
Investigated 2026-06-18 (c): the candidate portals are either undocumented JS
SPAs (PlanetBids) or require registration to download documents (Bonfire,
DemandStar) — which violates the public-data-only rule — so none is cleanly
crawlable today. Still backlog; needs a portal that publishes a documented
no-login listing+download API, or a partner/paid feed (owner decision).

### Crawl drawings only — SAM.gov as the active source
**Priority/LOE/Category/Status:** 6 / 2 / crawler / done (PR: this PR, 2026-06-18)
Of the four seeded sources, only SAM.gov attaches drawings; the three Socrata
permit datasets are signals with no documents. Paused the permit datasets
(`status=inactive`, kept + re-enableable in Admin) via seed + migration `0003`,
kept SAM.gov active with broadened casework keywords, and fixed attachment
download (`SAMGOV_API_KEY` appended to `sam.gov` resource links at fetch time,
never persisted). Feeds the new prospect detail view directly. SAM.gov key
(MA-008) is now load-bearing — no key, no prospects.

### Real pricing rates entered
**Priority/LOE/Category/Status:** 10 / 1 / pricing / backlog
MA-006. Quotes are blocked from `sent` until NEEDS REVIEW rates are replaced.

### Doors-aware pricing — Airtable $/ft² tiers + box→door/front decomposition
**Priority/LOE/Category/Status:** 9 / 7 / pricing / done (PR #216, 2026-06-23)
CabinetNow quote = 3 priced lists (doors/fronts by ft²×style, boxes per unit,
drawer-box hardware) − flat 10%. Shipped: Airtable-anchored $/ft² door tiers
(low/mid/high), cabinet-box pricing ported from pricing.js (0.3% vs live item),
drawer-box hardware formula (priceHardware → one rolled-up line), priceQuoteTiers
+ priceQuoteLineItems (single source of truth for the PDF). **Validated:**
MEDIUM −7% / HIGH +7% vs $27,733.68 Piestewa subtotal — within 10%.

### No-schedule reading: consistency hardening + tighter kitchen recall
**Priority/LOE/Category/Status:** 6 / 3 / takeoff / in-progress
Partial fix landed in `scribe/fix-truncated-region-drop` (branch, not yet merged):
temperature 0 on all four vision calls (classify/locate/extract/spreadsheet) stops
API-default 1.0 resampling; salvage parser + 32k max_tokens stops silent kitchen
drop. Remaining variance: vision is not bit-identical at temp 0, bath-vanity
sizing still flickers (77" master double), ~6-box gap vs the real 29-box quote
(Trash Base, Blind Corner, multi Base-Full-Height undetected). **Next session:**
audit prompt/locate prompt for remaining gaps; consider multi-pass verify or
deterministic rule-based corner injection.

### Estimate reading accuracy — most real CRM quotes within ±10%
**Priority/LOE/Category/Status:** 9 / 8 / takeoff / in-progress (2026-06-29)
Backtested 10 real CabinetNow quotes (Zoho CRM) through the estimate harness;
pricing validated, READING (box count) is the gap. Baseline 3/9 within ±10%
(see engineering-history 2026-06-29 + (b)). WIP on branch
`claude/elegant-hertz-3d705e` (merged in `scribe/estimate-reading-accuracy`, NOT
deployed). Ordered next steps:
1. ✅ **DONE (2026-06-29 b)** — ported harness fixes into `process.ts`
   (whole-page-once, non-estimate cross-page dedup, universal face expansion);
   cross-view collapse shared via `@scribe/shared`. Prod now == what was tested.
2. ✅ **DONE (2026-06-29 b)** — **median-of-N consensus** in the pipeline (shared
   `pickMedian`, env `ESTIMATE_CONSENSUS_N`, default 3). Q8 5/21/24 → 19/19/24;
   variance tamed. Scorecard after 1+2: still 3/9 (parity + stability, not accuracy).
3. ✅ **Research + count≠price (2026-06-29 c)** — consensus now selects by a
   quote-total proxy (`boxFaceArea`), not box count (same count can price −6% vs
   −28%). Tried prompt **v5** ("point-label-count"): net WORSE (over-reads complex
   plans), **reverted to v4**. **Settled config: v4 + area-consensus = 25% mean abs
   error, 3 solid (Q8/Q9/Q10) + 3 near-misses (Q3/Q5/Q6 ~13-14%).**
4. ✅ **Backtest harness + 21-quote dataset (2026-06-30).** Built `scripts/backtest.mjs`
   (+ importable `estimatePdf` / `--json`); test set 9 → **21 usable quotes**.
   Scorecard `~/Desktop/Scribe Testing/scorecard-21quotes.csv`: **8/21 within ±10%,
   12/21 within ~16%, mean abs err 44%.** Compare configs by MEAN ABS ERROR, not
   "X/N within 10%" (boundary noise).
5. ✅ **Over-read ROOT-CAUSED (2026-06-30).** Dominant failure (Q19 +257%, Q21 +176%
   /277 box, Q14 +169%, Q24 +132%, Q7 +60%). Diagnostics (boxes-by-page/room) show:
   an authoritative count exists, then **elevation pages RE-ENUMERATE the same
   cabinets** and the label-based dedup can't merge them (labels vary across views).
6. ✅ **Page-role router SHIPPED (PR #221, merged 2026-07-01).** `routeByPageRole`
   counts one authoritative role (`schedule > floor_plan > elevation`), drops
   demoted-role re-counts, drops fillers/crown from box pricing, retries socket
   errors. Backtest **MAE 59→34** — over-read tail gone (Q19 +421→+16, Q14 +178→+7).
7. ✅ **Text-layer schedule extractor (PR #224, merged 2026-07-01).** When a PDF's
   text layer holds a real cabinet TABLE, read it verbatim (0 vision). Nails
   itemized/spec inputs; fires on none of the 21 backtest docs (all drawings) so
   zero-regression. Also = the label-extraction technique for H2.
8. ✅ **H2 — reading-accuracy measurement (PR: this session, 2026-07-01 c).** The
   $-backtest was measuring LUCK. Built per-line ground truth (`extract-labels.mjs`
   → `labels.json`, 17/21 quotes / 361 cabinets from the real quote packets) + a
   reading scorer (`@scribe/shared scoreReading`, `score-reading.mjs`). **FIRST
   REAL BASELINE: recall 29% / precision 30% / F1 0.27** (N=1). size-error only 1.7"
   → the failure is COUNT/IDENTITY (detection), not sizing. Per class: labeled 0.35
   (best) > arch/image 0.17 > image/sketch 0.09. Q8 Piestewa (the "$ −7% showcase")
   = 36%/25% — $ hid a wrong read.
9. ✅ **H3 DECIDED = prompt/vision-only (owner, 2026-07-01 d).** Target is fully
   autonomous auto-send, BUT owner can't hand-label ("not a cabinet guy… needs to be
   a prompt to Claude or a vision API"). A trained detector needs localized (bbox)
   training data; the 361 labels have ZERO localization and a spike proved the VLM
   can't self-generate usable bboxes (`~/Desktop/Scribe Testing/q8-vlm-bbox-spike.png`)
   → **detector path off the table.** Stay on prompt/vision, tuned against the packet
   answer key via the ruler (no labeling needed). Send-gate also off (autonomous = no
   human-in-loop). Levers measured + ruled out: stronger model (Opus 4.8) = no win;
   router merge-not-drop = wrong direction on clean data.
10. ✅ **RULER FIXED + re-baselined (2026-07-01 d, commit 06c8abf).** The labels were
   polluted — packet "DOOR & DRAWER LIST" rows + fillers counted as cabinets. Now
   count the SAME priced box the reader does (`isCabinetBox`); labels 361→269. **TRUE
   baseline (clean, N=1): recall 41% / precision 31% / F1 0.32.** Failure FLIPPED to
   OVER-read / low-precision (Q7 +329%, Q14 +183%, Q24 +150%); some right-count-wrong-
   match (Q21 48/49, Q10 13/14) → size/identity gap. sparse 0.56 > labeled 0.41 >
   scan 0.35 > image 0.19 ≈ arch 0.17.
11. ✅ **LABELS v3 — header-driven packet parsing (2026-07-06).** A from-zero manual
   study (Claude-in-session reads; API key was out of credits) exposed THREE more
   ruler bugs: (a) packets with a leading `Cab#` column parsed **Cab# as the width**
   (Q11 gold was garbage); (b) packets print the schedule once per door-style option
   → carcasses double-counted (Q14); (c) the boxfix regex deleted real **"Wall
   Cabinet Door Over Door"** carcasses (Q14's 7 walls gone). Rebuilt
   `extractCabinetSchedule`: header-row column mapping (boundary ranges), width-
   anchored record assembly (wrapped names), money-header table skip (priced door
   lists), cross-page header carry (recovered HALF of Q8's truth: pantry talls +
   the 77" double vanity), reprint dedupe, qty column. Labels **269 → 299 units,
   18/21 quotes** (Q16 gap closed). Drawer-box hardware now excluded via
   `isNonBoxCasework` (also stops prod box-pricing it). **All pre-v3 baselines are
   invalid — re-run the scorer vs labels v3 when API credits return.**
12. ✅ **DIM-SKELETON grounding shipped GATED (2026-07-06, `DIM_SKELETON=1`).** The
   from-zero study's core insight: 17/21 inputs carry machine-readable printed
   dimensions WITH positions (text layer) — localization for free, the thing the
   VLM bbox spike proved it can't self-generate. Shared `dim-skeleton.ts` clusters
   dim strings into collinear chains (Q7's island prints its own cabinet split
   `6|27|24|24|27|6` under `124"`), suppresses sheet grid rulers, and renders a
   structured grounding block (assign-segments prompt + count-repeated-views-once
   rule) into `extractPage opts.grounding` via process.ts + the harness. Manual
   dimension-grounded reads scored vs labels v3: Q11 0.61 / Q7 0.47 / Q14 0.44.
13. ✅ **DIM_SKELETON A/B RUN (2026-07-06, owner's backtest-only API key, N=1,
   labels v3).** **TRUE pipeline baseline on the fixed ruler: F1 0.396** (R 35% /
   P 46%) — the old "0.32" was ruler artifact. Grounding arms: strict 0.378,
   additive 0.382 → **net wash, gate stays OFF**. Structure: helps mid/large
   structured docs (Q3/Q5/Q6/Q8/Q11/Q20/Q22 +0.04..+0.09; size-err 1.4→0.8"),
   POISONS small sparse-chain docs (Q16 0.50→0, Q24 0.53→0.22, Q13 0.29→0 — model
   re-sizes real cabinets to wrong chain values); even an ideal chain-richness
   gate only nets ~+0.01 (within N=1 noise). Sonnet one-shot cannot bind flat-text
   chains to pixels the way a multi-crop reader can — the same info scored F1
   ~0.44+ when read agentically (manual Claude reads, 7 quotes).
14. ⏭ **NEXT — the evidence now points at AGENTIC READING, not prompt tuning.**
   One-shot extraction is plateaued (global levers, model upgrade, and now
   grounding all refuted). The manual multi-crop dimension-grounded reads beat the
   pipeline on every class tested (arch 0.17→0.50, sketch 0.11→0.61). Build a
   gated agentic read path (tool loop: crop/zoom + emit-cabinets; ~5-10× vision
   cost, fine for $10k+ quotes). Cheaper salvage first: deterministic post-hoc
   width-snapping of predicted boxes to nearest chain value (captures the sizing
   win, zero recall risk). Still open: SCOPE-SUBSET decision (Q7 packet = 15 of
   ~27 drawn cabinets — intake scope input / CRM context / quote-whole-drawing
   policy; owner call), image path (SCR-005).

**Shipped merged 2026-07-01:** page-role router + non-box-casework + socket-retry
(#221); text-layer schedule extractor (#224). H2 eval infra in this session's PR.
All green, sharing `@scribe/shared` so the harness can't drift from prod.
Test assets: `~/Desktop/Scribe Testing/` — `backtest-quotes.json` (21), `labels.json`
(per-line truth), `reading-scorecard.csv`. See `[[scribe-crm-quote-backtest]]` memory.

### AI cross-validation toggle
**Priority/LOE/Category/Status:** 6 / 4 / takeoff / done (PR: this PR, 2026-06-16)
Admin → Branding & Freight "AI Cross Validation" toggle (`org_settings.
cross_validation_enabled`, migration 0002). Anthropic always extracts; when on
and `OPENAI_API_KEY` is set, each page is re-extracted with OpenAI (`gpt-4.1`,
`OPENAI_VISION_MODEL` override) using the same prompt/schema. The pure
`applyCrossValidation` comparator (`@scribe/shared`) diffs tag/qty/dims and
lowers the primary line confidence below the review threshold on disagreement
(never injects OpenAI-only lines). Best-effort: OpenAI failures warn, never
fail the takeoff. See MA-010.

### Validate seed Socrata field maps on first pull
**Priority/LOE/Category/Status:** 8 / 2 / crawler / backlog
MA-007. SF/LA/NYC dataset ids + field maps are best-effort config; fix via
Admin → Crawler Sources after the first run.

### Quote email drafting w/ PDF attached
**Priority/LOE/Category/Status:** 7 / 3 / backend / backlog
mailto can't attach files; today the rep downloads the PDF and attaches
manually. Draft via Gmail API or a compose deep-link with the signed PDF URL
in the body, from hank@cabinetnow.com. Still no automated sending (PRD §2).

### OCR fallback for scan-only PDFs
**Priority/LOE/Category/Status:** 7 / 5 / takeoff / backlog
PRD §4: tesseract fallback when vector text is absent and vision confidence
is low. Wire into `apps/workers/src/takeoff/process.ts` after extraction
confidence gating.

### Sheet-index classification shortcut
**Priority/LOE/Category/Status:** 6 / 4 / takeoff / backlog
PRD §6.2: read the cover-sheet index to pre-select candidate pages, confirm
by vision. Prompt already exists (`SHEET_INDEX_SYSTEM`); needs page-label →
page-number resolution. Current thumbnail batching is ~25 calls per 200
pages (within the <40 target), so this is an optimization, not a blocker.

### Prospect detail view — open project details + preview/send any discovered plan to takeoff
**Priority/LOE/Category/Status:** 6 / 2 / ui / done (PR: this PR, 2026-06-18)
The Prospect Queue only exposed Triage/Ignore + a `plan_set`-gated Run Takeoff
button — no way to inspect a prospect or see its drawings. Added a `View` button
→ new `/prospects/$projectId` route (`ProspectDetail.tsx`) showing all project
fields + score rationale and the full document list, each with an inline PDF
preview (presigned `/project-documents/:id/url` in an iframe + open-in-new-tab)
and a `Send to Takeoff` button, plus the prospect's source link(s)
(`sourceRefs[].url`, the crawl origin). Frontend-only — reuses existing endpoints
(`GET /projects/:id`, `GET /project-documents/:id/url`, `POST /takeoffs
{project_document_id}`); any document is sendable, not just `plan_set`, since
filename classification is rough.

### 2-step human review — page-picker gate + interactive box review on the approve screen
**Priority/LOE/Category/Status:** 8 / 7 / ui / done (PRs #233/#234 + follow-up,
2026-08-10/11)
Step 1: after a PDF upload, every page renders as a thumbnail
(`/takeoffs/$id/pages`); the estimator picks the pages to read and can
override each page's classifier-suggested type (the plan-vs-elevation call
decides reading accuracy). Step 2: extraction prices + expands immediately and
lands on the interactive review screen (`/takeoffs/$id`) — each detected
cabinet's bounding box is drawn over the EXACT image the model read (tabbed by
page: "Page 1", "Page 2", …), box↔line selection is linked both ways, boxes
and lines are editable (add by drawing / move / resize / delete; box edits are
visual anchors, the inch fields drive price), and pricing-relevant edits
re-match the line and re-derive its door/drawer faces server-side. Approve
locks it. Status flow `processing → awaiting_pages → processing → review →
approved`; the interim `awaiting_boxes` gate was removed 2026-08-11 (owner
feedback — legacy rows still finalize through the old endpoint). Spreadsheets
and text-layer schedule PDFs skip the page gate. BBoxes are advisory-quality
(loose) by design.

### Decompose + DIM_SKELETON prompt A/B on fresh reads
**Priority/LOE/Category/Status:** 8 / 3 / takeoff / backlog
Both levers are built and gated (`ESTIMATE_PROMPT=decompose`,
`DIM_SKELETON=1`) but unmeasured — a prompt change invalidates the saved read
kits, so this needs fresh API reads of the 10 test quotes (~$5, ask owner
first). Targets the two biggest residual error classes from the 2026-08-13
Wantoch audit: decomposition-convention clash (custom 57"/66" bases read as
smaller pieces) and height misreads (deep walls 33" vs printed 52.5").
Measure on the per-unit ruler; flip flags only on a win, like
ROUTER_TOLERANT_MERGE.

### Deterministic read checks (flag, never auto-fix)
**Priority/LOE/Category/Status:** 7 / 4 / takeoff / backlog
Zero-API sanity layer feeding the review screen's "Flagged for review" panel:
(a) sum of cabinet widths per run vs the sheet's printed run dimension (dim
chains already extracted); (b) bbox geometry now that every line carries one —
heavy overlap on the same image = suspected duplicate, box aspect wildly off
stated W×H = size misread, large drawn regions with no box = missed cabinets;
(c) plausibility ranges per category. Flag + highlight lines; the human
decides.

### Room-keyed cross-view reconciliation
**Priority/LOE/Category/Status:** 7 / 6 / takeoff / backlog
The tolerant merge dedups by size tolerance, so the same island read as 3×36"
(plan) and 21"/15" (elevation) survives twice, and the Wantoch dining towers
re-counted as "Living Room" talls (+$4.1k phantom). Make room identity the
reconciliation key: per room, pick the best view or merge within it, instead
of one global role precedence. Requires hardening room labels (today a string
normalization hack — "Kitchen" vs "Kitchen - North Wall").

### End-panel handling
**Priority/LOE/Category/Status:** 7 / 3 / pricing / backlog
Wantoch: 1.5"-wide tall END PANELS beside the fridge were read/priced as two
full 24×84×24 cabinets (+$3.2k). Reader should emit `panel` category for
end/filler panels (prompt nudge + tag regex exists in `isNonBoxCasework`), and
the tier engine should price panels as panels, not boxes.

### Collect numbered-unit ground-truth packets
**Priority/LOE/Category/Status:** 8 / 2 / algo / backlog (owner)
The Wantoch packet numbers every unit on the drawings (1–50) and keys the box
list to those numbers — gold-standard labels. Owner is collecting more real
quote examples with both the full plan set and the final itemized quote;
each becomes a labels.json row + read kit for the ruler.

### Review screen: click line → source region highlight
**Priority/LOE/Category/Status:** 6 / 5 / ui / done (absorbed by the two-stage
review gates, this PR, 2026-08-10)
Superseded/absorbed: the box-review gate delivers region-level provenance and
more — per-line `bbox_2d` from extraction, drawn over the exact read image,
with click box ↔ line linking and editable boxes. The only delta left is a
passive highlight on the post-finalize review screen; if ever wanted it rides
the same `takeoff_lines.bbox`/`read_image_key` columns.

### Eval fixture export job
**Priority/LOE/Category/Status:** 6 / 2 / algo / backlog
`eval_fixtures` rows (pre-correction + approved lines) → `evals/plansets/`
gold/predicted JSON, so the self-building corpus actually reaches `pnpm eval`.

### Remaining Wave-1 permit adapters
**Priority/LOE/Category/Status:** 6 / 3 / crawler / backlog
The generic Socrata adapter covers any SODA portal via config — add source
rows (dataset id + field map) for the remaining CA/FL metros; ArcGIS/Accela
portals need new adapter modules.

### Agenda-packet / state procurement adapter
**Priority/LOE/Category/Status:** 5 / 6 / crawler / backlog
PRD §5.6 wants ≥5 adapters incl. one agenda/bid source beyond SAM.gov.

### Plan-discovery first-page vision check
**Priority/LOE/Category/Status:** 5 / 3 / crawler / backlog
Doc classification is filename-heuristic only; add the PRD's first-page
vision confirmation (`DOC_CLASS_SYSTEM` prompt exists).

### bull-board + Sentry
**Priority/LOE/Category/Status:** 5 / 3 / ops / backlog
PRD §9. Mount bull-board on the API behind requireAdmin; SENTRY_DSN env is
already reserved.

### BigCommerce draft orders
**Priority/LOE/Category/Status:** 4 / 6 / backend / backlog
Endpoint stubbed (501). Needs a mapping from parametric lines to BigCommerce
products/custom line items.

### Dimension increments enforcement + dim-bounds editor UI
**Priority/LOE/Category/Status:** 4 / 3 / pricing / backlog
`increment_in` is stored but not enforced in `checkDimBounds`; the admin
editor doesn't expose dim bounds yet.

### Multi-unit/commercial extraction hardening
**Priority/LOE/Category/Status:** 5 / 6 / takeoff / backlog
PRD week 7. Current behavior: single unambiguous per-page multiplier is
applied; everything else flags for review. Harden against per-unit-type
schedules spanning pages once real corrected takeoffs exist.

### Pallet-heuristic tuning from actuals
**Priority/LOE/Category/Status:** 3 / 3 / algo / backlog
`quotes.actual_freight_cents` (manual entry) + dashboard est-vs-actual are
in; tune `pallet_config` once data accumulates.

### Uber Freight provider (v1.1)
**Priority/LOE/Category/Status:** 3 / 5 / backend / backlog
`FreightProvider` interface + stub exist; wire the real API, keep the
verification gate.

### Outreach email drafting in Prospect Queue (v1.1)
**Priority/LOE/Category/Status:** 2 / 4 / backend / backlog

### FL NOC + contractor-license adapters (v1.1)
**Priority/LOE/Category/Status:** 2 / 6 / crawler / backlog
