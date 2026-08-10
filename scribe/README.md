# sauce.ai / scribe

CabinetNow takeoff-to-quote pipeline + project prospector (PRD v1.2 in
`PRD.md` — the source of truth).

Ingests architectural plan sets (PDF), spreadsheets, and schedule photos;
extracts cabinet/casework line items with vision models + a deterministic
nomenclature parser; prices them against an admin-editable parametric pricing
model; and produces reviewable quotes with a mandatory freight-verification
gate. A public-data crawler proactively discovers construction projects with
≥ $35k cabinet scope and feeds them into the same pipeline. Approved takeoffs
export as Mozaik/KCD-importable CSV.

> New here? Read `WARMUP.md` (paste-in session prompt) →
> `new-engineering-session-instructions.md` → `engineering-history.md`.
> sauce.ai/news (repo root) and sauce.ai/signal (`signal/`) are DIFFERENT
> products — scribe lives entirely under `scribe/`.

## Stack (PRD §4, fixed)

- **Monorepo:** pnpm workspaces + Turborepo, TypeScript everywhere, Node 22.
- **Backend:** Fastify API; BullMQ + Redis workers; Postgres 16 (Drizzle);
  Cloudflare R2 (S3-compatible) for PDFs/artifacts.
- **AI:** Anthropic API — Sonnet-tier (`claude-sonnet-4-6`) for page
  classification + extraction vision, Haiku-tier (`claude-haiku-4-5`) for
  crawler filtering. Prompts versioned in `packages/prompts`.
- **Frontend:** React + Vite, TanStack Router/Query, Tailwind.
- **Deploy:** Railway — three services (api, web, workers) + Postgres +
  Redis plugins; see `INSTALL.md`.

## Layout

```
scribe/
├── apps/
│   ├── api/        # Fastify API: auth (Google OAuth), takeoffs, quotes,
│   │               # projects, admin (pricing editor, org settings,
│   │               # export templates, sources), quote PDF
│   ├── workers/    # BullMQ: takeoff pipeline in three gated stages
│   │               # (prepare/classify → extract → finalize/match) +
│   │               # crawler (fetch → normalize → score → plan-discovery
│   │               # → dedupe)
│   └── web/        # React SPA: Prospect Queue, Page Picker + Box Review
│                   # (the two takeoff gates), Takeoff Review (keyboard-
│                   # optimized), Quote Builder, Dashboard, Admin
├── packages/
│   ├── shared/     # zod schemas (CabinetLineItem etc.) + nomenclature
│   │               # parser (W3030/B24/SB36 → dims) + money utils
│   ├── pricing/    # pure parametric pricing engine + line→product matching
│   │               # + seeded product lines (rates marked NEEDS REVIEW)
│   ├── freight/    # FlatPalletProvider + pallet heuristic + Uber stub +
│   │               # freight-verification rule
│   ├── export/     # Mozaik/KCD CSV export, template-driven
│   ├── prompts/    # versioned prompt templates + model tier constants
│   ├── db/         # Drizzle schema, SQL migrations, idempotent seed
│   └── storage/    # R2/S3 helper (private bucket, signed URLs)
├── evals/          # extraction eval harness (pnpm eval) + fixtures
└── PRD.md INSTALL.md WARMUP.md roadmap.md bugs.md manual-actions.md
    engineering-history.md *-session-instructions.md
```

## Commands

```bash
pnpm install
pnpm build          # turbo: all packages
pnpm test           # 70+ unit tests (pricing/freight/export/nomenclature/
                    # spreadsheet/score/eval-metrics) — no DB or network needed
pnpm eval           # extraction eval suite; fails on >2pt regression
pnpm db:migrate     # apply packages/db/migrations/*.sql
pnpm db:seed        # product lines, pricing config v1, export templates,
                    # org settings, crawler sources, allowed users
```

Local dev needs Postgres 16 + Redis (`.env.example` lists every variable).
Without `GOOGLE_CLIENT_ID`, the API runs in dev-bypass mode (auto-login as a
local admin) — never set that combination in production.

## Load-bearing product rules

- **Two blocking human gates on every visual takeoff** (2026-08): after a PDF
  upload the estimator picks which pages to read (and can correct each page's
  type), and after extraction they review the model's bounding boxes over the
  exact images it read — add/move/resize/delete boxes, edit the linked lines —
  before anything is priced. Status flow: `processing → awaiting_pages →
  processing → awaiting_boxes → review → approved`. Spreadsheets skip both
  gates (nothing to pick or draw); text-layer schedule PDFs skip only the page
  gate.
- **Money is integer cents** everywhere internally.
- **Quotes pin a pricing_config version** — same lines + same version → same
  total, always. Admin saves create a new immutable version.
- **Send gates:** a quote cannot reach `sent` while (a) freight is unverified
  and the quote is ≥ $35k or has assembled casework, (b) any line prices
  against a seeded NEEDS REVIEW rate, or (c) unpriced lines remain.
- **Nothing is silently dropped:** unmatched lines land in the review
  screen's unmatched bucket; ambiguous unit multipliers flag for review.
- **Every approved takeoff feeds the eval corpus** (`eval_fixtures`:
  pre-correction extraction + approved lines).
