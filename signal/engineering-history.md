# sauce.ai/signal — engineering history

Chronological working history. Most-recent entries in full; older entries get
condensed into `engineering-history-archive.md` once this file approaches its
single-`Read` budget (~34 KB). The "Load-bearing state" and "PRD reference"
sections below are durable — never archive them.

---

## Load-bearing state (not in the repo — read first)

State that lives outside the repo and will reintroduce fixed bugs / break
deploys if a future session doesn't know it exists. Keep this current.

- **Not deployed yet.** As of 2026-06-08 signal exists only in-repo (Phase 0
  framework). There is no Railway project, no managed Postgres, no prod data.
  First-deploy actions are queued in `manual-actions.md` (Open).
- **DB requires PostGIS *and* pgvector.** `seed/schema.sql` runs
  `CREATE EXTENSION postgis | vector | pg_trgm`. The extension *binaries* must
  exist on whatever Postgres backs prod. Railway's bundled Postgres may not
  ship both; if not, use an external managed Postgres (Neon/Supabase/Crunchy)
  and point `DATABASE_URL` (with the `+psycopg` driver prefix) at it. This is
  the single most likely first-deploy blocker.
- **`DATABASE_URL` must use the `postgresql+psycopg://` scheme** (SQLAlchemy
  routes to psycopg3). A bare `postgres://` from a host's copy-paste will fail.
- **Seed jurisdiction field maps are best-effort** (`seed/jurisdictions.json`)
  and must be validated on first pull per city; a wrong map logs an error on
  the `IngestRun` row rather than crashing the run (by design).
- **The paid adapter is a disabled stub.** It only activates when
  `SIGNAL_PAID_API_KEY` is set AND a concrete client is implemented; until
  then it raises rather than making (paid) calls. Don't route a jurisdiction
  to `source_type=paid` without both.
- **Test-suite property:** the pure ingest/signal core
  (`app/adapters` except the Socrata HTTP path, `app/signals`,
  `app/ingest/dedup`) is intentionally dependency-free so
  `pytest signal/tests/` is green with only pytest installed. The
  FastAPI/SQLAlchemy boot tests are gated behind `importorskip`. Keep it that
  way — don't add heavy imports to the core.

---

## 2026-06-08 — Phase 0 framework + engineering system bootstrapped

**Context.** New product: sauce.ai/signal (PRD "Bloodhound"), a permit
intelligence & distressed-project triage tool. Goal of this session: stand up
the engineering paradigm (mirroring sauce.ai/news's process discipline) and
build the Phase 0 framework (PRD §15) on the PRD's prescribed — and
deliberately different from news — stack.

**Decisions (owner, this session).** Docs live under `signal/`; stub the paid
adapter behind the SourceAdapter interface (disabled); ship a minimal React
table this session; primary deploy target is **Railway**. PRD §13 decisions
(CRM target, free-vs-paid coverage policy, definitive seed metros, shippable
radius, 2,000-contacts export, hosting account) remain open — tracked in
`roadmap.md`.

**What shipped.**
- **Engineering system:** `README.md`, `INSTALL.md`, `WARMUP.md` (paste-in
  session prompt), `new-engineering-session-instructions.md`,
  `pm-session-instructions.md`, `engineering-session-wrapup.md`, and the
  tracking docs (`engineering-history.md`, `roadmap.md`, `bugs.md`,
  `manual-actions.md`). Root `.gitattributes` extended so the four signal
  tracking docs are `merge=union`. CI: `.github/workflows/signal-ci.yml` runs
  the pytest suite on PRs touching `signal/`.
- **Canonical schema** (`seed/schema.sql`): jurisdictions, projects, permits,
  inspections, contractors/contacts, signal_catalog + project_signals (EAV),
  saved_searches, rules, digests, ingest_runs, users — PostGIS geom +
  pgvector scope_embedding + pg_trgm.
- **Adapter layer** (`app/adapters/`): `SourceAdapter` base + canonical
  `NormalizedPermit` + `normalize_record` (field_map driven, date/number
  coercion, nested-location keys); generic **Socrata/SODA** adapter
  (pagination, app-token, incremental `$where`, exponential backoff); **paid**
  adapter stub; adapter **registry**.
- **Signal engine** (`app/signals/`): in-code **registry** (the catalog source
  of truth — ingested/derived/enrichment tiers, drives API facets);
  **derived** computations incl. all six distress signals, cabinet-relevance,
  value tier, category, stage, recency, geo/haversine, new-vs-known GC;
  composite **scoring** + a default "distressed commercial cabinet" rule.
- **Ingest** (`app/ingest/`): pure **dedup** (APN → address → permit) + DB
  **run orchestrator** (idempotent permit upsert → project assignment →
  recompute signals → score → IngestRun logging; one bad record/jurisdiction
  never aborts the rest).
- **API** (`app/`): FastAPI factory; `/health`, `/api/projects` (filterable,
  default sort `lead_score`, faceted), `/api/projects/{id}` (permits + signals
  + why-flagged), `/api/jurisdictions` (coverage/freshness), `/api/signals`
  (catalog/facets). All DB reads degrade to empty rather than 500.
- **Jobs** (`jobs/`): `init_db` (schema + seed signals/metros/default rule),
  `daily_ingest`, APScheduler `scheduler`.
- **Seed**: 7 Socrata metros (Chicago, NYC, LA, Austin, Seattle, SF, Dallas)
  with per-source field maps (flagged for first-pull validation).
- **Frontend** (`web/`): Vite + React + Tailwind + TanStack Table Projects
  view (default sort lead_score) with a registry-driven facet sidebar.
  Verified `npm run build` clean (TS strict).
- **Deploy**: `Dockerfile`, `docker-compose.yml` (Postgres+PostGIS+pgvector
  via `seed/docker-db`), `railway.json`, `.env.example`.

**Tests.** 40 passing (`python -m pytest signal/tests/ -q`): adapter
normalization, Socrata pagination (mocked), paid-stub gating, dedup, derived
signals incl. distress, scoring, registry integrity, seed-file validity, and
app-boot/graceful-degradation (gated on web stack).

**Code touched.** New `signal/` tree (see `README.md` layout); root
`.gitattributes`; new `.github/workflows/signal-ci.yml`.

**Deploy/infra state touched.** None (not deployed). First-deploy actions
queued in `manual-actions.md`.

**PRs.** This PR — Phase 0 framework + engineering system for sauce.ai/signal.

**Open items.** Resolve PRD §13 decisions; validate seed field maps on first
real pull; wire the Anthropic semantic pass (PRD §9, currently rules
baseline); add simple auth (PRD §10); first Railway deploy. See `roadmap.md`.

---

## PRD reference

The full v1 PRD ("Permit Intelligence & Distressed-Project Triage Tool",
drafted 2026-06-06) is the product source of truth. Key framing a future
session must keep in mind:

- **No single national permit API.** Normalize many jurisdictions onto one
  schema; the dominant free platform is **Socrata** (now Tyler "Data &
  Insights"). Also expect ArcGIS and Accela/eTRAKiT/CityView portals.
- **Coverage is a long tail.** "National" is filled over time, not day one.
- **Distress is rarely a field — it must be DERIVED** (status/date/inspection
  anomalies). **The signal engine is the core IP, not the scraper.**
- **Phasing (§15):** 0 skeleton → 1 signal engine + scoring + digest → 2
  ArcGIS + Socrata auto-discovery + map + CRM push → 3 portal scrapers +
  freshness dashboard → 4 enrichment (liens/litigation/news) + contact
  resolution + full LLM classification.
- **§13 open decisions** (resolve early): CRM target, free-vs-paid coverage,
  seed metros, shippable radius, 2,000-contacts export, hosting.
- **Compliance (§16):** respect each portal's ToS/robots/rate limits, prefer
  official APIs over scraping, no CAPTCHA bypass; every Project links back to
  its source records (provenance).
