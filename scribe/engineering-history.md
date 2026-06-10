# sauce.ai/scribe — engineering history

Chronological working history. Most-recent entries in full; older entries get
condensed into `engineering-history-archive.md` once this file approaches its
single-`Read` budget (~34 KB). The "Load-bearing state" and "PRD reference"
sections below are durable — never archive them.

---

## Load-bearing state (not in the repo — read first)

State that lives outside the repo and will reintroduce fixed bugs / break
deploys if a future session doesn't know it exists. Keep this current.

- **Not deployed yet.** As of 2026-06-10 scribe exists only in-repo. There is
  no Railway project, no prod DB, no R2 bucket, no Google OAuth client.
  First-deploy actions are queued in `manual-actions.md` (MA-001…MA-008).
- **Dev-bypass auth:** with `GOOGLE_CLIENT_ID` unset and
  `NODE_ENV != production`, every API request authenticates as a local admin
  (`dev@scribe.local`). Prod MUST set `GOOGLE_CLIENT_ID`/`SECRET` and
  `NODE_ENV=production`.
- **Railway build shape:** each service's root directory is `scribe` (the
  monorepo root is the Docker context); config-as-code lives at
  `scribe/apps/<svc>/railway.json`. The web image bakes `VITE_API_URL` at
  BUILD time — changing the API domain requires a web rebuild.
- **Runtime images use `pnpm --filter <pkg> --prod deploy --legacy /out`** —
  verified to produce a standalone runnable bundle (workspace deps' dist +
  db migrations included). Docker daemon wasn't available in the build
  sandbox, so the full `docker build` is unverified — treat the first Railway
  build as a verification step.
- **Seeded pricing rates are placeholders** (`needs_review: true`); the API
  blocks `sent` quotes that price against them. Seeded Socrata field maps
  (SF/LA/NYC dataset ids + columns) are best-effort and must be validated on
  first pull (MA-007).
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

**PRs:** this PR — v1 framework.

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
