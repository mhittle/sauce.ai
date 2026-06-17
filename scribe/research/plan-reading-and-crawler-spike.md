# Research spike — better plan reading + PlanHub-style deal discovery

**Date:** 2026-06-17 · **Type:** research-only (no production code shipped) ·
**Owner ask:** (A) read small/illegible text on architectural plans, (B) produce
estimates from plans with no distinct cabinet schedule, (C) flesh out the web
crawler to find cabinet-related plan sets / deals like PlanHub.

This document is a design/spec to decide what to build next. Each section ends
with a recommendation + rough LOE. Nothing here is wired into the pipeline yet.

Web access for this spike: confirmed (WebSearch + WebFetch).

---

## Background: what the extractor does today

`apps/workers/src/takeoff/process.ts` → `processPdf`:

1. mupdf rasterizes **every page to a 50-DPI thumbnail** → Sonnet
   (`claude-sonnet-4-6`) batch-classifies each page
   (`cabinet_schedule_table` / `finish_schedule` / `kitchen_or_millwork_elevation`
   / …). See `packages/prompts/src/classify.ts`.
2. Pages whose class is in `RELEVANT_PAGE_CLASSES` are re-rendered **once each at
   a fixed 200 DPI** (`EXTRACTION_DPI` in `apps/workers/src/takeoff/pdf.ts`) and
   sent to Sonnet as **a single full-page image** (`extract.ts` →
   `EXTRACT_SYSTEM`).
3. Output is zod-validated, run through the deterministic `repairLine` parser,
   matched to product lines, and queued for review.

Two structural facts drive tasks A and B:

- **The extraction model is `claude-sonnet-4-6`** (`packages/prompts/src/index.ts:11`).
- **One full page → one image, at a fixed DPI, with no cropping/tiling.**

---

## A) Small / unreadable text on large sheets

### Root cause (confirmed against Anthropic's vision docs)

Claude **downscales any image larger than the model's native resolution before
it ever sees it.** From the vision reference
(`platform.claude.com/docs/en/build-with-claude/vision`):

| Model | Native resolution (long edge) | Visual-token budget |
|---|---|---|
| **Sonnet 4.6 (what we use today)** | **1568 px** | 1568 tokens |
| Opus 4.7 / 4.8 / Fable 5 | **2576 px** | 4784 tokens |

Claude tokenizes in 28×28-px patches and resizes to the largest aspect-preserving
size satisfying **both** the edge limit and the token-budget limit. Whichever
binds first triggers the resize — and for tall portrait sheets the **token
budget binds well before the edge limit** (the docs' own example: a 1075×1520
page is under 1568 px on both sides but costs 2145 tokens, so it's resized down
to 924×1307).

Now apply that to a real plan sheet. An ANSI/Arch **E-size sheet is 34"×44"**.
Our 200-DPI render is **6800×8800 px**. Sonnet downscales that to ~**1211×1568**
— a **0.18× scale factor**. A schedule cell's 1/8"-tall text (~25 px at 200 DPI)
lands at **~4.5 px** by the time the model sees it: illegible. This is exactly
the owner's report. The 200-DPI render is wasted work — we send 60 MP and the
model reads 1.9 MP.

So the DPI knob alone can't help: rendering higher just gets downscaled harder.
**The fix is to keep the region we care about at or below the model's native
resolution so no downscaling happens** — i.e. crop/tile, not zoom.

### Options

**A1 — Upgrade the extraction model to a high-res-vision model (Opus 4.8).**
Doubles the long edge (1568→2576) and ~3× the token budget. Cheapest change
(swap `SONNET_MODEL` usage in `extract.ts` for an Opus id). But a full E-sheet
still downscales to ~1990×2576 (0.29×) — 25 px text → ~7 px. Helps marginally,
**does not solve it**, and ~1.7× the input-token cost per image (Opus $5/MTok
vs Sonnet $3/MTok, plus up to 4784 vs 1568 tokens/image). Use as a complement,
not the fix.

**A2 — Region-crop the schedule, then read it (recommended core).** The
classify pass already tells us *which* pages are schedule tables. Add one cheap
step: ask the model (on the thumbnail or a mid-DPI render) for the **bounding
box of the schedule/table region** in pixel coords (the vision API is explicitly
good at this — "Return `[x1,y1,x2,y2]` in pixel coordinates"). Then rasterize
**only that crop** at a DPI chosen so its long edge ≈ the model's native
resolution (≤1568 px Sonnet / ≤2576 px Opus). Result: the schedule fills the
whole image at ~1:1 — full legibility, no wasted pixels.

**A3 — Deterministic tiling fallback (recommended, pairs with A2).** When no
clean table bbox is found (busy elevations, schedules split across the sheet,
bbox step low-confidence), fall back to **fixed grid tiling**: split the
high-DPI page render into overlapping tiles each sized to the native resolution
(e.g. 2–3 columns × 3–4 rows with ~10% overlap so no row of text is cut), run
extraction on each tile, then **dedupe lines across tiles** (overlap + the
existing `parseTag`/`repairLine` identity gives a natural dedup key:
tag+room+dims). More model calls per page, but each tile is read at full
fidelity. Per-takeoff token budget already guards cost; tiling must respect it.

**A4 — Vector-text fast path (worth a look, separate from vision).** Many plan
PDFs carry real vector text (CAD exports), not scans. mupdf can extract text +
positions directly (`page.toStructuredText`) with zero model cost and zero
resolution loss. Where a schedule is vector text, parse it deterministically and
skip vision entirely; fall back to vision for scans/rasters. This also feeds the
existing OCR-fallback roadmap item. Biggest accuracy win per dollar if the test
plan sets turn out to be vector PDFs.

### Recommendation for A

Ship **A2 (bbox-crop) + A3 (tiling fallback)** as the core, keep extraction on
Sonnet but make the model id a config knob so **A1** (Opus high-res) is a
one-line toggle for hard sets, and spike **A4** (vector-text fast path) against
real plans first — it may make a chunk of A2/A3 unnecessary for CAD exports.

The render pipeline change is localized: `pdf.ts` grows a `renderRegion(page,
bbox, targetLongEdgePx)` helper that picks DPI from the target pixel size;
`process.ts` gains the bbox step + tile loop; `extract.ts` is unchanged except
it's now called per-region. New prompt: `SCHEDULE_BBOX_SYSTEM` (bump prompt
version). **Needs an eval fixture from a real large-format sheet** before/after
to prove the lift — ties directly into the top roadmap item ("Validate
extraction on real plan sets").

**LOE ≈ 5–6** (takeoff). Risk: line dedup across tiles, and coordinate mapping
(must rescale against the *resized* dimensions, not padded — see vision docs
"How Claude resizes and pads images").

---

## B) Plans with no distinct cabinet schedule

### The problem

Today the pipeline only extracts from pages classified as
`cabinet_schedule_table` / `finish_schedule` / `kitchen_or_millwork_elevation`.
A plan set with **no cabinet schedule at all** (common on smaller residential
jobs and design-bid sets) yields **zero lines** — there is nothing to count.
Industry practice (per the takeoff guides surveyed) is to estimate cabinetry off
the **floor plan + interior elevations** by measuring **linear feet** of base
and upper runs, kept separate (their $/LF differs), then translating LF into
priced units.

### What the research says estimators actually do

- **Measure straight-line wall runs** of base vs. upper cabinetry, in inches,
  ÷12 = linear feet; uppers and lowers are priced separately.
- **Elevations are where box counts live** when there's no schedule — read each
  interior elevation, count and size the boxes drawn on it, and cross-reference
  the plan for run lengths. Modern takeoff tools (PlanSwift, STACK, Houzz Pro,
  Exayard) digitize exactly this: linear measure on the plan + box counts off
  elevations.
- **Linear-foot pricing is genuinely ambiguous** ("a LF = base only" vs "base +
  upper together") — so any estimate we produce must be **explicitly labeled
  with its method and assumptions**, not presented as a precise takeoff.

### Options

**B1 — Elevation-driven box extraction (recommended).** We already classify
`kitchen_or_millwork_elevation` pages and even rank them as a supplement. Extend
the extractor so that **when no schedule page exists**, elevations become the
primary source: prompt the model to enumerate every cabinet box drawn, infer
width from dimension strings / scale, and emit lines with **lower confidence +
an `estimated` flag** (so the review screen and pricing treat them as estimates,
never as schedule-grade lines). Reuses the whole existing line/match/review
path; the only new thing is an estimate provenance flag.

**B2 — Linear-foot scope estimate from the floor plan (recommended companion).**
When even elevations are thin, fall back to a **scale-aware LF measurement**: get
the plan's scale (title-block scale or a dimensioned reference), have the model
trace base/upper cabinet runs, compute LF, and produce a **rough-order-of-
magnitude $ estimate** (LF × a configurable $/LF for base and upper). This is a
*scope* number for the prospect/quote-triage stage, not a line-item quote —
gate it behind a clear "ROM estimate" banner and **never let it flow into a
`sent` quote** (consistent with the NEEDS-REVIEW send gate). Store the $/LF rates
in `pricing_config` so they're versioned like everything else.

**B3 — "No schedule found" as a first-class outcome.** Regardless of B1/B2,
when classification finds no schedule the takeoff should surface a clear status
("no cabinet schedule detected — estimated from elevations / floor plan") rather
than silently returning few/zero lines. Pure UX/plumbing, small.

### Recommendation for B

Do **B3** (the honest-status plumbing) as table stakes, then **B1**
(elevation-driven extraction with an `estimated` flag) as the real capability.
Treat **B2** (LF ROM estimate) as a follow-on once B1 has real fixtures to
calibrate against — it depends on reliable scale detection, which is the risky
part. **B depends on A**: you can't count boxes on an elevation the model can't
read, so the bbox-crop/tiling work lands first.

Hard guardrails (PRD-aligned): estimated lines carry an `estimated`/low-confidence
flag, are visibly distinguished in review, and the ROM $ number is **blocked
from `sent` quotes** just like NEEDS-REVIEW rates. Don't silently drop, don't
silently assume.

**LOE ≈ 6** (takeoff/pricing), B1 ≈ 4 of that. Needs real no-schedule plan sets
as fixtures.

---

## C) PlanHub-style discovery of cabinet plan deals

### What PlanHub (and peers) actually are

From the platform research: **PlanHub, ConstructConnect/iSqFt, Dodge
PlanRoom/Network, BidClerk** are **gated, login-walled, paid bid-management
networks**. GCs upload construction documents and invite subs by trade; subs
browse a project finder, download plans from a plan room, and submit bids. The
plans and project data live **behind authentication and subscriptions**, and the
terms of service prohibit scraping. So "be like PlanHub" splits into two very
different things:

1. **PlanHub-the-product** (a bid board / plan room you log into) — a gated
   commercial network. We can't crawl it, and rebuilding it is out of scope.
2. **PlanHub-the-value** (a feed of relevant projects with downloadable plan
   sets, filtered to cabinet/casework work) — this is what the owner wants, and
   it's an **extension of the crawler we already have.**

### What we already have

`apps/workers/src/crawler/` is a config-driven crawler with a
`fetchSince(cursor)` adapter interface, polite fetch (1 req/s/host, honest UA),
heuristic + Haiku scoring (`score.ts`), dedupe, and **plan-discovery** (downloads
linked PDFs to MinIO `prospect-docs/`, sha256-dedup). Adapters today:
`socrata.ts` (any SODA government portal) + `samgov.ts` (federal procurement).
The whole design is **public-data-only**, which is the legally clean lane.

### The defensible way to get "PlanHub-style" plan deals

Mirror the existing philosophy: **public plan rooms and e-procurement portals,
not the gated networks.** These publish bid solicitations *with attached plan
sets* and are explicitly meant to be downloaded:

- **Government e-procurement / public plan rooms** — state & municipal bid
  portals (many on **Bonfire, OpenGov/ProcureNow, Periscope/BidNet, DemandStar,
  Ionwave, PlanetBids**), school-district and university capital-projects pages,
  GSA/PBS. These post RFPs/ITBs with downloadable drawings — the richest public
  source of *plan sets we're allowed to fetch*.
- **The Socrata adapter already covers a slice** (permit datasets) — but permits
  are *signals of work*, not *plan sets*. The new value is portals that attach
  **actual drawings** we can run a takeoff on.
- **AIA/association "open" plan rooms and free public plan rooms** where access
  is genuinely open (verify per-site ToS).

### What to build

**C1 — A public-plan-room adapter (recommended core).** A new adapter type
behind the existing `SourceAdapter`/`fetchSince` interface for one e-procurement
platform family (start with whichever covers the owner's target metros — likely
**Bonfire** or **BidNet/DemandStar**, which expose listings programmatically).
It normalizes solicitations into the existing `projects` shape and lets
plan-discovery download attached drawing PDFs into `prospect-docs/` exactly as
today. Config-driven so adding portals = adding source rows, matching the
Socrata pattern.

**C2 — Cabinet-relevance scoring on discovered plans (recommended).** Extend
`score.ts` so a project/plan is ranked for **casework relevance** (keywords:
casework, millwork, cabinets, kitchen, lab/clinic/dorm/multifamily fit-out;
negative: pure sitework/structural/MEP). High-relevance prospects with a
downloaded plan set get a **one-click "Run Takeoff"** straight into the pipeline
(the Prospect Queue already has this affordance). This is the actual product
loop: discover → score → takeoff → quote.

**C3 — First-page vision confirmation for discovered plans.** The roadmap
already has "plan-discovery first-page vision check" — confirm a downloaded PDF
is a real plan set (not an addendum/spec/cover letter) before queuing. Cheap,
improves the signal of the C1/C2 feed.

### What NOT to do

- **Do not scrape PlanHub / ConstructConnect / Dodge / BidClerk.** Login-walled,
  paid, ToS-prohibited, and a real legal/account-ban risk. If the owner wants
  *their* leads from those, the right move is the platform's own API/partner
  program or a paid data feed — a procurement/legal decision, not an
  engineering one. Flag for the owner; don't build a scraper.
- Keep the politeness rules (1 req/s/host, honest UA + contact email, public
  data only) — they're PRD acceptance criteria and they're also what keeps the
  public-portal lane defensible.

### Recommendation for C

Build **C1 (one public-plan-room adapter) + C2 (casework relevance scoring)** as
the MVP of "PlanHub-style discovery," with **C3** as a fast follow. Pick the
portal family by where the owner's customers actually bid. Explicitly tell the
owner the gated networks are off-limits to crawl and require a paid/partner feed.

**LOE ≈ 6** (crawler), C1 ≈ 4 of that. Risk: each e-procurement platform has its
own listing format; the first adapter is the expensive one, subsequent portals
on the same platform are config.

---

## Suggested sequencing

1. **A4 spike first** (half-day): are the owner's real plan sets vector PDFs or
   scans? Determines how much of A is even a vision problem.
2. **A2 + A3** (bbox-crop + tiling) — the highest-leverage accuracy fix, and a
   prerequisite for B. Land with a real before/after eval fixture.
3. **B3 + B1** (no-schedule status + elevation extraction) once A makes
   elevations legible.
4. **C1 + C2** (public-plan-room adapter + casework scoring) — independent of
   A/B, can run in parallel by a second session.

Each is its own branch/PR. None of this is built yet — this doc is the decision
input.

---

## Validation against real plan sets (2026-06-17)

Owner provided four real sets. Inspected with `pdfinfo` / `pdffonts` / rendered
crops. These confirm the analysis and sharpen it. (Files contain client PII —
"Weiss Residence", a street address — so they are **not** committed here; they
live on the owner's machine and are strong fixture candidates pending consent.)

| Set | Size | Text layer | What it is | Maps to |
|---|---|---|---|---|
| 2440 Piestewa "Floor Plan" | **36×24″ (Arch D)** | vector, embedded **+ unicode** | large-format floor plan | **A** |
| KITCHEN FLOOR PLAN & ELEVATIONS | **36×24″ (Arch D)** | vector, embedded + unicode | enlarged plan + interior elevations + dimension callouts | **A** |
| Highland Model B | **A1, rotated 90°** | Type 1, **not embedded, `uni: no`** | 3D model export; cover renders + a floor-plan-only sheet | **B (hardest)** |
| Design.pdf | letter, 9 pp | vector, embedded | kitchen plan + numbered `ELV` callouts → elevations | **A + B1** |

**A is confirmed empirically.** Rendering the 36″ kitchen sheet down to Sonnet's
1568 px (what the model sees today): elevation *titles* legible, but the
dimension callouts and notes are ~4–8 px and unreadable. Cropping a single
elevation and rendering it at native 150 DPI (no downscale) makes the **same
content fully legible** — the dimension run (`1 1/2"`, `24"`, `36"`, `21"`…),
`FARMHOUSE SINK`, `DISHWASHER (CUSTOM PANEL)`, `INDUCTION RANGE`,
`PARIS-INSET CABINETS / COLOR: BEIGE`, `4" ROLL-OUT TRAY IN DRAWER`, scale
`1/2"=1'-0"`. Same pixel budget reaching the model; the only change is not
squashing the whole sheet. This is the A2/A3 fix, proven.

**New finding — "schedule-first" is the wrong default for residential.** *None*
of these four sets contains a tabular cabinet schedule. The cabinet data lives
in **dimensioned interior elevations** and **plan callouts**, not a
`cabinet_schedule_table`. The current pipeline ranks schedules first and treats
elevations as a supplement; real residential sets invert that. Recommend the
classifier/extractor treat elevations + dimensioned plans as first-class
sources, not fallbacks. (Doesn't change the §A mechanism, but raises §A's
priority and reshapes §B.)

**A4 (vector-text fast path) is viable for 3 of 4** — Piestewa, Kitchen, and
Design all carry embedded vector text with a unicode map (extractable with zero
model cost / zero downscaling). **Highland is the exception:** Type 1 fonts,
not embedded, no ToUnicode (`uni: no`) → the text layer is unreliable, so
Highland must go through vision. So A4 helps a lot but can't be the only path.

**B splits into two real sub-cases (confirmed):**
- **B1 — set has elevations** (Design.pdf, and the kitchen set): count boxes off
  the elevations. This is the common, tractable case.
- **B2 — floor-plan-only, no elevations** (Highland): the *only* cabinet signal
  is kitchen/bath/closet runs drawn in plan (island, `DW`, `Range`, vanities,
  W.I.C). Estimate must come from **scale-aware linear-foot measurement of the
  plan** (Highland's title block gives `1/4"=1'-0"`). Highland is the hardest
  case on every axis — 3D export, no schedule, no elevations, no usable text
  layer — so it's the right worst-case fixture for B2, but B1 is where to start.

**Net effect on recommendations:** §A unchanged in approach, higher priority
(it's the gate for everything and real sets are large-format with tiny text).
Add: stop treating schedules as the primary source. §B: build B1 (elevations)
first; B2 (LF-from-plan) is a harder follow-on that Highland exercises. §A4:
worth doing for the vector-text majority, with vision as the fallback for
non-embedded sets like Highland.

---

## Sources

- Anthropic Vision reference (resolution limits, downscaling, tokenization):
  https://platform.claude.com/docs/en/build-with-claude/vision
- PlanHub — how the bid board / plan room works:
  https://planhub.com/ , https://planhub.com/bid-board/
- ConstructConnect / Dodge plan rooms & bid platforms:
  https://www.constructconnect.com/solutions/subcontractors ,
  https://www.construction.com/the-7-best-construction-bid-platforms-in-2026/
- Cabinet linear-foot estimating & takeoff-from-elevations methodology:
  https://sinclaircabinets.com/how-to-calculate-linear-feet-for-cabinets/ ,
  https://upgradedhome.com/calculate-linear-feet-kitchen-cabinets/ ,
  https://www.buildxact.com/us/blog/construction-takeoff/
