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
| v1 framework — monorepo, takeoff pipeline, pricing, freight, quotes, UI, crawler, evals | 10 | 9 | infra | done |
| First Railway deploy (api/web/workers + PG + Redis + MinIO) | 10 | 4 | ops | done |
| Validate extraction on real plan sets + first real eval fixtures | 10 | 5 | takeoff | backlog |
| Legible large-format reads — schedule bbox-crop + tiling (research: research/plan-reading-and-crawler-spike.md §A) | 8 | 6 | takeoff | backlog |
| Estimate from plans with no cabinet schedule — elevation/LF extraction (research: spike §B) | 6 | 6 | takeoff | backlog |
| Public-plan-room crawler adapter + casework relevance scoring (PlanHub-style discovery; research: spike §C) | 6 | 6 | crawler | backlog |
| AI cross-validation toggle (secondary OpenAI extraction → lower confidence on disagreement) | 6 | 4 | takeoff | done |
| Real pricing rates entered (clear NEEDS REVIEW) | 10 | 1 | pricing | backlog |
| Validate seed Socrata field maps on first pull | 8 | 2 | crawler | backlog |
| Quote email drafting w/ PDF attached (replace mailto) | 7 | 3 | backend | backlog |
| OCR fallback for scan-only PDFs (tesseract) | 7 | 5 | takeoff | backlog |
| Sheet-index classification shortcut | 6 | 4 | takeoff | backlog |
| Review screen: click line → source region highlight | 6 | 5 | ui | backlog |
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

### Legible large-format reads — schedule bbox-crop + tiling
**Priority/LOE/Category/Status:** 8 / 6 / takeoff / backlog
Root cause confirmed: Sonnet 4.6 downscales any image past 1568px long edge, so
a full E-size sheet rendered at 200 DPI (6800×8800) is squashed to ~1211×1568
and schedule text becomes ~4px tall. Fix is to crop the schedule region (vision
bbox step) and/or tile the page, rendering each region at ≤ the model's native
resolution so text stays ~1:1 — not to raise DPI (which only gets downscaled
harder). Optionally make the extraction model a config knob (Opus 4.8 = 2576px
high-res). Vector-text fast path worth a spike first. Full analysis +
options in `research/plan-reading-and-crawler-spike.md` §A.

### Estimate from plans with no cabinet schedule
**Priority/LOE/Category/Status:** 6 / 6 / takeoff / backlog
When a plan set has no schedule table, today's pipeline returns ~0 lines.
Extend to count boxes off interior elevations (lower-confidence, `estimated`
flag) and, as a follow-on, a scale-aware linear-foot ROM $ estimate gated like
NEEDS-REVIEW (never flows to a `sent` quote). Depends on §A (elevations must be
legible first). See spike §B.

### Public-plan-room crawler adapter + casework relevance scoring
**Priority/LOE/Category/Status:** 6 / 6 / crawler / backlog
"PlanHub-style" discovery done the defensible way: crawl public e-procurement
plan rooms (Bonfire/BidNet/DemandStar/PlanetBids/OpenGov etc.) that publish
solicitations with downloadable drawings — NOT the gated PlanHub/ConstructConnect/
Dodge networks (login-walled, paid, ToS-prohibited; need a paid/partner feed,
an owner decision). New adapter behind the existing `fetchSince` interface +
casework-relevance scoring in `score.ts` → one-click Run Takeoff. See spike §C.

### Real pricing rates entered
**Priority/LOE/Category/Status:** 10 / 1 / pricing / backlog
MA-006. Quotes are blocked from `sent` until NEEDS REVIEW rates are replaced.

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

### Review screen: click line → source region highlight
**Priority/LOE/Category/Status:** 6 / 5 / ui / backlog
PRD §7.1 calls for region-level provenance; v1 shows the full source page.
Needs extraction to return per-line bounding boxes (model supports it) and
an overlay renderer.

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
