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
- **`railway.json` startCommand must be `sh -c`-wrapped.** Railway execs the
  start command without a shell, so a bare `$PORT` is passed literally
  (`Invalid value for '--port': '$PORT'`). The command is
  `sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'`.
- **DB image inits into a PGDATA subdir.** `seed/docker-db` sets
  `PGDATA=/var/lib/postgresql/data/pgdata`. Railway (and most managed) volumes
  leave a `lost+found` at the mount root, which makes `initdb` refuse a
  non-empty data dir and crash-loop. Mount the volume at
  `/var/lib/postgresql/data`; don't remove that ENV.
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

## 2026-06-09 — Web UI: server-side sort + click-through project detail

**Context.** Deployed Phase-0 table was read-only — no useful sort (only the
loaded page sorted client-side) and no way to open a project.

**What shipped.**
- API: `/api/projects` sort is now a whitelist map (added `jurisdiction`→
  `j.name`, `category`, `status`, `primary_address`) + a `dir` (asc|desc)
  param. Detail endpoint already existed.
- Web: clickable column headers drive **server-side** sort/paging (Prev/Next,
  50/page, total count); rows are clickable and open a **detail drawer**
  (`ProjectDrawer.tsx`) showing lead score, why-flagged contributions, all
  signals, and the permit timeline with source-record links. Dropped the
  `@tanstack/react-table` dep (hand-rolled table; bundle 197→150 KB).

**Code touched.** `app/api/projects.py`; `web/src/{api,App,ProjectsTable}.tsx`,
new `web/src/ProjectDrawer.tsx`, `web/package.json`; `tests/test_app.py`
(sort/dir accepted). 44 tests green; web build clean.

**PRs.** UI functionality PR (this).

---

## 2026-06-09 — Web frontend: production Dockerfile (nginx) for Railway

**Context.** `web/` only built to static files; needed a way to deploy it.

**What shipped.** `web/Dockerfile` (multi-stage: Node build → nginx serve) +
`web/default.conf.template` (SPA fallback, `listen ${PORT}` via the nginx
image's envsubst) + `web/.dockerignore`. Deploy as a Railway service with Root
Directory `signal/web`; `VITE_API_BASE` (API public URL) is inlined at build
time. Docs: INSTALL §2.4, MA-006.

**Deploy/infra note.** Live deploy in progress this session. Earlier deploy
gremlins resolved: Railway volume `lost+found` (PGDATA subdir, #175); Railway
startCommand `$PORT` not shell-expanded (#176); special-char DB password URL
parse error (PG* vars, #177); and a **`PGDATA` env-var value typo** (value was
`PGDATA=/var/lib/postgresql/data/pgdata` — stray prefix → Postgres wrote to
ephemeral fs, wiping data every redeploy). Fix: set the value to the bare path.
Chicago (~3.6k) + Cincinnati ingested and persisting.

**PRs.** Frontend Dockerfile PR (this).

---

## 2026-06-09 — DB config: encode special-char passwords (PG* vars)

**Context.** Setting `DATABASE_URL` with an `openssl rand -base64` password
(contains `+ / =`) crashed every DB request with
`sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL` — the unescaped
password broke URL parsing in `get_session`'s dependency (a 500 that
`/health/db`'s try/except can't catch, since it fires before the handler body).

**Fix.** `config.resolve_database_url()` now prefers `DATABASE_URL` but falls
back to discrete `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`, assembling the
URL via `sqlalchemy.URL.create()` which **encodes the password safely** — set
`PGPASSWORD` raw, no manual encoding. Docs updated (`.env.example`,
`INSTALL.md`, MA-002). Immediate unblock for a live service: give the DB role
an alphanumeric password (`ALTER ROLE signal PASSWORD '...'` via the DB
service Console) and use it raw in `DATABASE_URL`.

**Code touched.** `signal/app/config.py`; `signal/tests/test_config.py` (3
tests, +43 total); docs.

**PRs.** Follow-up deploy-hardening fix.

---

## 2026-06-09 — Fix: Railway startCommand `$PORT` not expanded

**Context.** API service crash-looped: `Error: Invalid value for '--port':
'$PORT' is not a valid integer.` Railway runs `railway.json`'s `startCommand`
without a shell, so `$PORT` was passed literally (the Dockerfile `CMD` already
wraps in `sh -c`, but startCommand overrides it).

**Fix.** Wrap the startCommand:
`sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'`. Immediate
unblock for a live service is the same string as a UI custom start command.

**Code touched.** `signal/railway.json`; `engineering-history.md`.

**PRs.** Follow-up deploy fix.

---

## 2026-06-09 — Fix: DB image crash-loops on Railway volume (PGDATA subdir)

**Context.** First Railway deploy of the `seed/docker-db` Postgres service
crash-looped: `initdb: error: directory "/var/lib/postgresql/data" exists but
is not empty ... lost+found`. Railway's volume leaves a `lost+found` at the
mount root, so the postgis image's `initdb` refused to initialize.

**Fix.** Bake `ENV PGDATA=/var/lib/postgresql/data/pgdata` into
`seed/docker-db/Dockerfile` so Postgres inits into an empty subdirectory of the
mount. Documented in `INSTALL.md` §2 + `manual-actions.md` MA-001 + the
Load-bearing state section. Immediate unblock for an already-created service is
the same `PGDATA` env var on the service.

**Code touched.** `signal/seed/docker-db/Dockerfile`; docs (`INSTALL.md`,
`manual-actions.md`, this file).

**PRs.** Follow-up PR (deploy fix) off the merged Phase 0 framework.

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
