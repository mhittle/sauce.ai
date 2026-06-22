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
  casework_base with "Filler"/"End Panel" in the tag so [[expand.ts]] skips
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

---

## PRD reference

The full product spec is `scribe/PRD.md` (v1.2, June 2026 — final). Key
invariants enforced in code: integer-cents money; immutable pricing-config
versions pinned per quote; freight-verification gate (≥ $35k or assembled
casework); NEEDS-REVIEW rate send block; unmatched lines never dropped;
ambiguous unit counts flag rather than assume; per-takeoff and daily-crawler
token budgets; crawler politeness rules (1 req/sec/host, honest UA, public
data only).
