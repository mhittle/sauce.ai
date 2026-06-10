# PRD: CabinetNow Takeoff-to-Quote Pipeline + Project Prospector

**Version:** 1.2 — June 2026 (final; supersedes v1.1; all blockers resolved)
**Owner:** Mike (CTO)
**Audience:** Claude Code (implementation agent). This document is the source
of truth. No open questions remain — proceed. Where judgment is needed, prefer
the simplest implementation that satisfies acceptance criteria.

> **Timeline note (supersedes §11):** the owner compressed the timeline to
> 48 hours for the first deployable build. §11's 8-week milestones still
> describe the build order; weeks 1–4 remain the revenue-critical path.

v1.2 changes: admin-editable parametric pricing model (no external pricing
source), per-quote manual markup (no tiers), $700/pallet flat freight with
FreightProvider interface for later Uber Freight integration, branding/terms
managed via admin uploads, Mozaik/KCD CSV export promoted into v1, eval
fixtures sourced from first live takeoffs.

---

## 1. Problem & Goal

CabinetNow.com sells custom cabinet products online (BigCommerce storefront):
cabinet doors, drawer fronts, drawer boxes, and full casework (flat-pack or
assembled) in many materials/finishes, plus closet systems. The catalog is
parametric — items are priced from dimensions, material, and finish rather
than fixed SKUs.

Large B2B buyers (GCs, multifamily developers, kitchen dealers, remodelers;
deals ≥ $35k) are won or lost on quote turnaround speed and accuracy. Today,
quoting a plan set means an estimator manually re-enters everything into
Mozaik (reps also work in KCD/2020) — days of overhead per large quote. Big
projects are also discovered reactively (inbound only).

**Goal:** Ship a system that:

1. Ingests architectural plan sets (PDF) — plus spreadsheets/photos/item
   lists — and produces an accurate, reviewable quote in < 15 minutes,
   eliminating Mozaik re-entry for quoting purposes.
2. Exports approved takeoffs as Mozaik/KCD-importable CSV so orders that
   still flow through design software skip manual re-entry there too.
3. Proactively discovers construction/remodel projects from public data
   sources, surfaces those with ≥ $35k cabinet scope, and feeds them into an
   outreach + quoting workflow.

**North-star metric:** dollar value of quotes issued per week, and
quote-to-order conversion on deals ≥ $35k.

## 2. Non-Goals (v1)

- No CAD/geometry modeling, no CNC/CAM output, no native Mozaik/KCD file
  formats (CSV export only).
- No automated quote sending without human approval. Every quote passes a
  review gate.
- No scraping of paid/gated services (Dodge, ConstructConnect,
  BuildingConnected, PlanHub). Public data only.
- No installed-price (labor) estimating. Product + freight only.
- No customer tiers or automated discounting — markup/discount is a manual
  per-quote decision.
- No live freight rating in v1 (flat per-pallet model; Uber Freight later via
  provider interface).
- No multi-tenant SaaS. Internal tool.

## 3. Users & Roles

| Role | Who | Needs |
|---|---|---|
| Estimator (primary) | Estimator/sales rep (Mozaik background) | Upload plans or pick prospected project → review extracted takeoff → fix flagged lines → approve → quote PDF → send; export CSV for Mozaik |
| Inside sales | Rep (KCD/2020 background) | Same flow for inbound mixed-format requests (spreadsheets, photos, lists); export CSV for KCD |
| Sales lead / Admin | Mike | Prospect queue triage, dashboard, pricing model editor, freight config, branding/terms, crawler config |

Auth: Google OAuth, role field on user. No self-signup. Quote emails draft
from hank@cabinetnow.com.

## 4. System Overview

Three subsystems in one monorepo:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  A. PROSPECTOR  │────▶│  B. TAKEOFF      │────▶│  C. QUOTE &     │
│  (public-data   │     │  ENGINE          │     │  PIPELINE UI    │
│  crawler)       │     │  (input → line   │     │  (review, price,│
│                 │     │  items → params) │     │  send, export)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                        ▲
        └── projects w/ plans ───┘   Manual upload (PDF/XLSX/CSV/images) also enters at B
```

### Tech stack (fixed)

- Monorepo: pnpm workspaces + Turborepo. TypeScript everywhere.
- Backend: Node 22, Fastify (or Hono), Postgres 16 (Drizzle ORM), BullMQ +
  Redis, S3-compatible object storage (Cloudflare R2) for PDFs/artifacts.
- Frontend: React + Vite, TanStack Router/Query, Tailwind + shadcn/ui.
- AI: Anthropic API. Sonnet-tier model for page classification and schedule
  extraction (vision on rasterized pages); Haiku-tier for cheap crawler
  filtering. All prompts versioned under `packages/prompts/`.
- PDF tooling: mupdf/pdfium (WASM) for splitting/rasterizing at 200–300 DPI;
  tesseract OCR fallback when vector text is absent and vision confidence is
  low. SheetJS for XLSX/CSV intake and CSV export.
- Deploy: Railway — services: api, web, workers; Railway Postgres + Redis
  plugins; R2 for objects. GitHub Actions CI: typecheck, lint, unit tests,
  eval suite (§10), deploy on main.

Packages layout:

```
apps/web            # React UI
apps/api            # Fastify API
apps/workers        # BullMQ workers (crawler, extraction, pricing)
packages/db         # Drizzle schema + migrations
packages/prompts    # versioned prompt templates + few-shot examples
packages/pricing    # pure parametric pricing engine (no IO) — heavily unit tested
packages/freight    # pure freight estimator behind FreightProvider interface
packages/export     # Mozaik/KCD CSV export with configurable column mappings
packages/shared     # zod schemas, types
```

## 5. Subsystem A — Prospector (public-data project crawler)

### 5.1 Purpose

Continuously discover construction/remodel projects likely to carry ≥ $35k
cabinet/millwork scope, with attached or linkable plan sets and public
business contact info.

### 5.2 Sources (v1, priority order)

1. Municipal building permit open-data APIs (Socrata/ArcGIS/Accela portals).
   Wave 1 jurisdictions: CA, FL, NY metros — e.g., Los Angeles, San Diego,
   San Jose, Sacramento, San Francisco; Miami-Dade, Orlando, Tampa,
   Jacksonville; NYC DOB NOW/open data plus Long Island/Westchester portals
   where available. Jurisdiction list is config, not code. Wave 2 expands
   nationally (we ship anywhere).
2. Public procurement / bid boards — SAM.gov (federal), CA/FL/NY state
   procurement portals, public school district and housing-authority RFP
   pages. These frequently attach full plan sets as public PDFs.
3. Planning commission / city council agenda packets — early pipeline signal
   for multifamily/mixed-use.
4. v1.1: FL Notice of Commencement databases; state contractor-license
   project filings.

### 5.3 Compliance rules (hard requirements)

- Respect robots.txt and published API rate limits. Default ≤ 1 req/sec/host,
  exponential backoff on 429/5xx.
- Public, unauthenticated data only. Never bypass logins, paywalls, or
  CAPTCHAs; mark such sources blocked.
- Honest User-Agent with contact email.
- Provenance (source URL + retrieval timestamp) on every record.
- Business contacts only, as published in public records. No data-broker
  enrichment in v1.

### 5.4 Pipeline stages (BullMQ jobs)

1. **fetch** — per-source adapter pulls new records since cursor. Interface:
   `fetchSince(cursor) -> RawRecord[]`. One adapter module per source; cron
   per source (default 6h).
2. **normalize** — canonical Project shape (zod-validated).
3. **filter/score** — Haiku-tier call + heuristics → cabinet_relevance_score
   0–100 and est_cabinet_scope_usd (heuristic from project type, unit count,
   valuation). All project types in scope (multifamily, SFR builders,
   hospitality, government/education, large remodels); projects with
   estimated cabinet scope < $35k are deprioritized (below the fold), not
   deleted. Negative signals: roofing, paving, MEP-only, demo.
4. **plan-discovery** — download linked PDFs to R2; classify
   `plan_set | spec_book | other` (filename heuristics + first-page vision
   check).
5. **dedupe** — fuzzy match on address + parcel + permit number across
   sources; merge.
6. **enqueue** — score ≥ threshold (default 60) → Prospect Queue. Projects
   with a plan set get one-click "Run Takeoff".

### 5.5 Data model (Prospector)

```
sources(id, name, type, base_url, config jsonb, status, last_cursor, created_at)

projects(id, canonical_address, jurisdiction, permit_number, project_type,
         valuation, est_cabinet_scope_usd, description, gc_name, gc_contact jsonb,
         status [new|triaged|quoting|quoted|won|lost|ignored], assigned_to,
         cabinet_relevance_score, score_rationale text,
         source_refs jsonb[], created_at, updated_at)

project_documents(id, project_id, s3_key, doc_class, page_count, sha256,
                  fetched_from_url, fetched_at)
```

### 5.6 Acceptance criteria

- ≥ 5 adapters live (≥ 3 CA/FL/NY permit portals, SAM.gov, ≥ 1 agenda/bid
  source).
- Idempotent crawls (no duplicate projects on re-run).
- ≥ 50 scored projects in queue within first week of operation.
- Provenance links on every project.

## 6. Subsystem B — Takeoff Engine (input → line items → parametric products)

### 6.1 Inputs

- Plan set PDF (10–300+ pages) — dominant format for the biggest fish.
- Spreadsheets (XLSX/CSV) and photos/screenshots of schedules or item lists —
  common for mid-size inbound. Spreadsheet intake is a deterministic
  column-mapping flow with model-assisted header inference (cheap, no vision).

### 6.2 Stage 1 — Page classification (PDFs)

Rasterize thumbnails, batch-classify pages:
`cover/index | floor_plan | kitchen_or_millwork_elevation |
cabinet_schedule_table | finish_schedule | spec_text | other`.

Optimization: read the sheet index first (sheet names like "A6.1 INTERIOR
ELEVATIONS", "ID-501 MILLWORK SCHEDULE") to pre-select candidates, then
confirm by vision. Goal: classify a 200-page set with < 40 full-resolution
vision calls.

### 6.3 Stage 2 — Line-item extraction

For each relevant page (schedules first; elevations as supplement), render at
high DPI and extract structured line items. Zod schema:

```
CabinetLineItem = {
  source_page: number,
  tag: string | null,            // "B24", "W3030", "SB36"
  room: string | null,
  qty: number,
  category: "casework_base"|"casework_wall"|"casework_tall"|"vanity"|"closet"
            |"door"|"drawer_front"|"drawer_box"|"panel"|"filler"|"trim"
            |"hardware"|"countertop"|"unknown",
  width_in: number | null,
  height_in: number | null,
  depth_in: number | null,
  door_style: string | null,
  material: string | null,       // "maple", "MDF", "PLAM", ...
  finish: string | null,         // incl. paint/stain spec when present
  assembled: boolean | null,     // flat vs assembled — line option only
  notes: string | null,
  confidence: number             // 0–1, per line
}
```

Rules:

- Parse standard nomenclature (W3030 → wall 30"w × 30"h; B24 → base 24"w;
  SB36 → sink base 36"w; default depths: base 24", wall 12", tall 24").
  Encode in prompt reference table AND in a deterministic post-parser that
  validates/repairs model output.
- Multi-unit projects: detect unit types and counts ("Unit A ×24, Unit B
  ×12"), extract per-unit-type schedules, multiply. If unit counts are
  ambiguous, flag for review — never silently assume.
- Per-line and per-document confidence; lines < 0.8 flagged. Document summary
  lists uncertainties and unreadable pages.
- Persist raw model output + page image refs for audit.

### 6.4 Stage 3 — Parametric pricing (admin-editable standard model)

There is no external pricing source of truth. The system owns a standard
parametric pricing model that admins configure entirely through a UI.
`packages/pricing` is pure and deterministic; all variables live in versioned
pricing_config rows.

Pricing model (per product line):

```
line_price = qty × [ base_rate × size_measure
                     + finish_adder
                     + assembly_adder (if assembled)
                   ]
quote_subtotal = Σ line_price
quote_total = (subtotal × (1 + markup_pct) + handling_charge + freight)
```

Where, configurable per product line in the Admin Pricing Editor:

- size_measure: linear feet (width-based), square feet (width × height), or
  per-unit — admin selects the measure per product line.
- base_rate: $ per LF / per sqft / per unit, set per material (editable
  material × rate grid).
- finish_adder: $ or % per finish option (e.g., painted vs natural), editable
  grid.
- assembly_adder: $ or % when assembled = true.
- handling_charge: quote-level flat $ (admin default, editable per quote).
- markup_pct: manual per-quote field (positive or negative) — no tiers, no
  automated discounts. Defaults to 0; estimator sets a unique markup/discount
  per job. Margin display next to it (role-gated to admin/sales lead).
- Dimension bounds (min/max W/H/D, increments) per product line;
  out-of-bounds lines go to the unmatched bucket.

Admin Pricing Editor requirements:

- CRUD product lines; per-line: size measure, material-rate grid,
  finish-adder grid, assembly adder, lead-time days, dimension bounds, active
  flag.
- Every save creates a new immutable pricing_config version; quotes store the
  version they were priced against → quotes are always reproducible.
- "Test calculator" panel: enter a sample line (category, dims, material,
  finish, assembled) and see the computed price live against the draft config
  before saving.
- Seed the database with sensible starter product lines (doors, drawer
  fronts, drawer boxes, framed casework, frameless casework, closet parts)
  with placeholder rates clearly marked NEEDS REVIEW so the admin screen is
  populated on first run.

Mapping: each CabinetLineItem → product line + validated parameters (dims
within bounds, material/finish resolved against config lists via fuzzy
match). Output match_confidence + up to 3 alternates. No-match items
(out-of-bounds dims, unrecognized constructions, non-carried items like
countertops) land in an "unmatched" bucket for manual resolution — never
dropped.

Lead times: every quote line displays its product-line lead time (e.g.,
framed maple: next-day; painted doors: 4 weeks). Quote shows max lead time
prominently; mixed lead times trigger a "split shipment?" prompt.

### 6.5 Freight module

`packages/freight`, pure and unit-tested, behind a FreightProvider interface:

- v1 provider: FlatPalletProvider — $700/pallet (admin-editable rate). Pallet
  count estimated from line dims/volume/assembled-state via a simple packing
  heuristic (config: pallet dims 48×40×72", max weight 1,500 lb, assembled
  casework packs at ~40% volumetric efficiency, flat product at ~75%; all
  editable). Round pallets up.
- UberFreightProvider stub: define the interface
  (`quote(shipment: ShipmentSpec) -> FreightQuote`) and a stub implementation
  now; wire the real Uber Freight API integration in v1.1. Provider selection
  is config.
- Every quote ≥ $35k or containing assembled casework gets a mandatory
  "freight verified" checkbox in review — estimator must confirm or override
  the freight number before the quote can be sent. (Shipping is the #1
  historical quoting error; this gate is non-negotiable.)
- Log estimated vs actual freight on won orders (manual entry) to tune the
  pallet heuristic.

### 6.6 Data model (Takeoff/Quote)

```
product_lines(id, name, size_measure [lf|sqft|unit], material_rates jsonb,
              finish_adders jsonb, assembly_adder jsonb, dim_bounds jsonb,
              lead_time_days, active)

pricing_configs(id, version, snapshot jsonb, created_by, created_at)   -- immutable versions

takeoffs(id, project_id nullable, uploaded_by, source_file_s3_key,
         source_kind [pdf|xlsx|csv|image],
         status [processing|extracted|review|approved|failed], page_count,
         classified_pages jsonb, doc_confidence, created_at)

takeoff_lines(id, takeoff_id, ...CabinetLineItem fields..., product_line_id nullable,
              resolved_params jsonb, match_confidence, alternates jsonb,
              reviewer_edited bool)

quotes(id, takeoff_id, customer_id nullable, status [draft|sent|won|lost|expired],
       pricing_config_id, subtotal, markup_pct, handling_charge,
       freight, freight_pallets, freight_verified bool, total,
       valid_until,           -- created_at + 10 days (price lock policy)
       max_lead_time_days, pdf_s3_key, bigcommerce_draft_order_id nullable,
       sent_at, created_at)

customers(id, company, contact jsonb, bigcommerce_customer_id nullable)

org_settings(id, logo_s3_key, quote_terms_md, quote_footer_md,
             default_handling_charge, pallet_rate, pallet_config jsonb,
             updated_by, updated_at)
```

### 6.7 Acceptance criteria

- 50-page residential set end-to-end < 10 min wall-clock.
- Eval set (§10): ≥ 95% line-item recall; ≥ 97% qty/dimension accuracy on
  high-confidence lines; zero silent drops.
- Quotes reproducible: same lines + same pricing_config_id → same total,
  always.
- No quote reaches `sent` without freight_verified = true.
- Admin can change a material rate and see it reflected in the test
  calculator and in new quotes (old quotes unchanged).

## 7. Subsystem C — Quote & Pipeline UI

### 7.1 Screens

1. **Prospect Queue** — scored projects (score, est. scope $, type,
   jurisdiction, has-plans badge); assignable; actions: ignore, assign, Run
   Takeoff, view source docs.
2. **Takeoff Review** — split view: source page/sheet left (zoom/pan),
   extracted lines right; click line → source region. Inline edit;
   low-confidence highlighted; unmatched bucket with product-line + parameter
   picker. "Approve takeoff" gate.
3. **Quote Builder** — priced lines with per-line lead time; manual markup %
   field (margin display role-gated); handling charge; freight panel (pallet
   count + $700/pallet, override allowed, mandatory verification checkbox);
   terms from org settings incl. "customer must verify all measurements and
   quantities" and 10-day validity. Generates branded quote PDF (server-side,
   R2). Optional BigCommerce draft order. "Send" opens drafted email from
   hank@cabinetnow.com with PDF attached (no automated sending in v1).
   "Export CSV" button: Mozaik or KCD format (§7.3).
4. **Pipeline Dashboard** — quotes by status, $ quoted/won per week,
   turnaround time, conversion by source, estimated-vs-actual freight.
5. **Admin** — Pricing Editor (§6.4); freight/pallet config; Branding &
   Terms: logo upload (PNG/SVG → org_settings), editable quote terms and
   footer (markdown); crawler sources/jurisdictions; prompt versions; CSV
   export mapping editor.

### 7.2 UX requirements

- Review screen is the product. Keystroke-optimized: arrow-key navigation,
  `e` edit, `enter` accept, batch-accept high-confidence lines.
- Extraction provenance everywhere (page thumbnail per line).
- Money in cents internally; USD display.

### 7.3 Mozaik/KCD CSV export (v1 — required)

`packages/export`:

- Export an approved takeoff (or quote) as CSV shaped for import into Mozaik
  or KCD cutlist/catalog import.
- Implementation: configurable column-mapping templates (export_templates
  table: name, target [mozaik|kcd|generic], ordered column defs mapping
  takeoff-line fields → CSV headers, unit format, delimiter). Ship
  best-effort default templates for Mozaik and KCD; an admin mapping editor
  lets the reps adjust headers/order/units to match their import dialogs
  without code changes (import dialect varies by version — the mapping editor
  is the safety valve).
- Acceptance: rep exports a takeoff, adjusts mapping once in admin if needed,
  and successfully imports into their tool; mapping persists.

## 8. API surface (representative)

```
POST /takeoffs                    (multipart PDF/XLSX/CSV/image | {project_document_id})
GET  /takeoffs/:id
PATCH /takeoff-lines/:id
POST /takeoffs/:id/approve
GET  /takeoffs/:id/export.csv?template=
POST /quotes                      ({takeoff_id, customer_id?})
PATCH /quotes/:id                 (markup_pct, handling_charge, freight override)
POST /quotes/:id/verify-freight
POST /quotes/:id/pdf
POST /quotes/:id/draft-order
GET  /projects?status=&min_score=&assigned_to=
PATCH /projects/:id
GET/PUT /admin/pricing            (product lines, rates; creates new version)
GET/PUT /admin/org-settings       (logo, terms, pallet config)
GET/PUT /admin/export-templates
GET  /admin/sources  POST /admin/sources/:id/run
```

All bodies zod-validated from `packages/shared`.

## 9. Security & ops

- Secrets via Railway env vars: ANTHROPIC_API_KEY, BIGCOMMERCE_*,
  DATABASE_URL, REDIS_URL, R2_*.
- Plan PDFs may contain client info — R2 private, signed URLs, 90-day
  lifecycle on prospected docs (config).
- bull-board behind admin auth; pino structured logs; Sentry.
- Cost guardrails: per-takeoff token budget with hard cap; daily crawler
  model-call budget; alerts on breach.

## 10. Eval suite

`evals/plansets/` with hand-labeled ground truth (CabinetLineItem JSON). Seed
strategy: weeks 1–2, use public plan sets (crawler finds, or grab from public
bid boards manually); from week 4 internal launch onward, every real takeoff
the reps correct becomes a labeled fixture automatically (store pre-correction
extraction + post-review approved lines; the diff is ground truth). This
replaces the earlier ask for historical plan sets — the system self-builds
its eval corpus from live usage.

`pnpm eval` reports recall/precision/field accuracy per set and aggregate; CI
fails on > 2-point regression vs main.

Pricing + freight: pure unit tests with golden fixtures generated from the
seeded pricing config.

## 11. Milestones (original 8-week plan; compressed to 48h — see header)

| Week | Deliverable |
|---|---|
| 1 | Monorepo scaffold, schema, PDF upload → page classification; XLSX/CSV intake; eval harness with first public plan sets; pricing engine core + seeded product lines |
| 2 | Extraction + nomenclature parser hitting eval targets on residential sets; Admin Pricing Editor with test calculator; org settings (logo/terms upload) |
| 3 | Freight module (FlatPalletProvider + verification gate); Takeoff Review UI (usable) |
| 4 | Quote builder + PDF + markup field + BigCommerce draft orders + Mozaik/KCD CSV export with mapping editor. Internal launch: reps quoting real inbound on the system; review corrections start feeding the eval corpus |
| 5 | Prospector: 3 CA/FL/NY permit adapters + scoring + Prospect Queue |
| 6 | SAM.gov + agenda adapters; plan-discovery auto-handoff; dedupe |
| 7 | Multi-unit/commercial extraction hardening (eval corpus now includes real corrected takeoffs); dashboard; pallet-heuristic tuning from actuals |
| 8 | Ops hardening, cost guardrails, docs, v1.1 backlog triage |

Weeks 1–4 are the revenue-critical path. Crawler work must not slip into
weeks 1–4.

## 12. Risks & mitigations

- **Placeholder pricing rates shipped to a customer:** seeded rates are
  marked NEEDS REVIEW; quote builder blocks `sent` status if any line prices
  against a NEEDS REVIEW rate. Admin must enter real rates before first
  external quote.
- **Freight misquotes:** flat $700/pallet is crude — mandatory verification
  gate + estimator override + actuals logging; Uber Freight provider in v1.1.
- **Extraction on messy scans:** OCR fallback, confidence gating,
  fast-correction review UI; never auto-send.
- **CSV import dialect drift (Mozaik/KCD versions):** admin mapping editor is
  the safety valve; no code change needed.
- **Crawler fragility:** isolated adapters; per-source health in admin.
- **Token cost on 300-page sets:** thumbnail-first, sheet-index shortcut,
  hard budgets.

## 13. Resolved decisions (formerly open questions)

- **Pricing:** standard parametric model owned by the system; all
  rates/variables ($/LF or $/sqft per material, finish adders, assembly
  adder, handling charge) entered via Admin Pricing Editor. Versioned
  configs; quotes pin their version.
- **Discounts:** no tiers. Manual per-quote markup % (unique per job).
- **Freight:** $700/pallet flat (editable) with pallet-count heuristic;
  FreightProvider interface with Uber Freight integration deferred to v1.1;
  mandatory verification gate stays.
- **Eval fixtures:** self-building corpus — public plan sets to start, then
  every rep-corrected live takeoff becomes ground truth automatically.
- **Branding/terms:** admin uploads logo and edits terms/footer markdown in
  org settings; quote PDF renders from these.

## 14. v1.1 backlog (do not build in v1)

- Uber Freight API integration via existing FreightProvider interface.
- FL Notice of Commencement + contractor-license adapters; national
  jurisdiction wave 2.
- Outreach email drafting (model-generated first-touch from project context)
  in the Prospect Queue.
- Pallet-heuristic auto-tuning from logged actuals.
- Native Mozaik/KCD file formats (beyond CSV) if CSV import proves lossy.
