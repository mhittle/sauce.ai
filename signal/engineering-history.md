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

## 2026-06-09 — Detail-page document fetch (the bid packages)

**Context.** CivicPlus list pages carry only the bid's detail link, not the
attachments — so solicitations had no plan/spec docs.

**What shipped.** `HtmlConfigAdapter` now supports a `detail` config block: per
list row, it fetches the bid's detail page and extracts attachment links
(degrades to [] on failure). Baked into the CivicPlus pattern via
`.relatedDocuments a[href*="DocumentCenter"]`, so all 208 CivicPlus sources now
pull their **bid packages** (incl. plan sets) into `solicitation_documents` →
the Solicitations drawer, inline PDF viewer, and `has_docs` filter. Document
type is guessed from the link text (plans/spec/addendum/attachment).

**Validated live:** Gainesville bid 177 → 3 docs incl. "Compiled Plans"
tagged `plans` + "Addendum No 1" tagged `addendum`.

**Perf note.** Detail fetch = 1 extra GET per bid, so `ingest_procurement.py
--all` now makes far more requests (hundreds–thousands across 208 sources).
Fine for a scheduled job; revisit with concurrency/politeness if it gets heavy.

**Code touched.** `app/adapters/solicitations/config_source.py`;
`tests/test_procurement_config.py`. 62 tests green.

**PRs.** Detail-doc-fetch PR (this).

---

## 2026-06-09 — Solicitations: Source column + source filter

**What shipped.** Solicitations table gained a **Source** column (`source_type`)
and a **source dropdown filter** in the sidebar. New `GET
/api/solicitations/sources` returns distinct `source_type`s with counts (drives
the dropdown; declared before `/{solicitation_id}` so "sources" isn't parsed as
an int). The list endpoint already supported the `source_type` filter param.

**Code touched.** `app/api/solicitations.py`, `app/schemas.py`
(`SourceCountOut`); `web/src/{api.ts, SolicitationsTable.tsx, SolicitationsView.tsx}`;
`tests/test_app.py`. 61 tests green; web build clean.

**PRs.** Source-filter PR (this).

---

## 2026-06-09 — Scale-out: 200+ CivicPlus sources via auto-discovery

**Context.** "Run 200 more." Hand-writing 200 entries = guesswork; instead
built discovery that finds real CivicPlus municipalities and emits verified
config.

**What shipped.**
- Compact **`civicplus` platform** in `build_config_adapter`: an entry needs
  only `{slug, domain, state}`; the adapter synthesizes the validated CivicPlus
  config (`civicplus_config`/`civicplus_list_url`). Keeps the seed small at scale.
- `jobs/discover_civicplus.py`: pulls the CISA `dotgov-data` .gov list (~11k
  city/county domains), probes each `Bids.aspx` open page concurrently for the
  CivicPlus marker, and seeds only domains with **current open bids** (verified,
  immediately useful). Slug/domain dedup; respectful single GET per host.
- Ran it (two passes): `procurement_sources.json` now has **210 sources** —
  206 CivicPlus municipalities with open bids across 30+ states (MA/TX/NY/OH/
  VA/GA/CA/FL…), all `active`. The 2 GA references converted to the compact form;
  GPR/Bonfire kept as inactive drafts.

**Ingest:** `python jobs/ingest_procurement.py --all` now pulls every active
source into the Solicitations tab. (~12% of probed city/county .gov domains had
open CivicPlus bids.)

**Code touched.** `app/adapters/solicitations/config_source.py` (civicplus
platform), `jobs/discover_civicplus.py` (new), `seed/procurement_sources.json`
(210), `tests/test_procurement_config.py`, `INSTALL.md`. 60 tests green.

**PRs.** Scale-out PR (this).

---

## 2026-06-09 — First live procurement sources: CivicPlus (GA cities)

**Context.** Tuned the first real sources against live pages (I have web access
in-session). DemandStar/Bonfire are JS SPAs (uncurlable); GSFIC/GPR were
sparse/ASP.NET. Winner: **CivicPlus `Bids.aspx`** — server-rendered, and the
identical module runs on thousands of municipalities, so one config
generalizes by domain swap.

**What shipped.** Validated `HtmlConfigAdapter` end-to-end against
**Gainesville, GA** (6 open construction bids w/ real close dates) and
**Marietta, GA** (extraction confirmed on 110 rows) and seeded both **active**
in `procurement_sources.json` (CivicPlus pattern: `.listItemsRow.bid` →
title/source_url/bidID/status/close-date). Added a fixture regression test
locking the CivicPlus row shape. Fixed `parse_date` to accept CivicPlus's
`M/D/YYYY H:MM AM/PM` (no-seconds) datetimes.

**How to add a CivicPlus city:** copy the `ga-marietta` block, change
`base_url`/`list_url`/`state`, run `validate_procurement_source.py`, flip
`active`. (Plan PDFs are on each `bids.aspx?bidID` detail page = `source_url`;
list-only for now — detail-page doc fetch is the next follow-up.)

**Code touched.** `seed/procurement_sources.json` (2 active GA sources),
`app/adapters/base.py` (date format), `tests/test_procurement_config.py`
(CivicPlus fixture). 58 tests green.

**PRs.** First-live-sources PR (this).

---

## 2026-06-09 — Config-driven procurement-source framework (adapter library)

**Context.** SAM.gov (federal) is the wrong firehose for commercial/MF leads;
the public bids + plans live on state/county/local procurement systems. Owner
wants to OWN the aggregation (not pay Shovels/PlanHub) by building a library
of adapters. Decision: make sources **config-driven** (like Socrata field maps)
rather than one-off scrapers.

**What shipped.** `app/adapters/solicitations/config_source.py`: generic
`JsonConfigAdapter` (SPA/JSON portals — Bonfire/OpenGov style, dotted field
paths, stdlib) + `HtmlConfigAdapter` (server-rendered lists — CSS row/field
selectors via BeautifulSoup), both parameterized by a source config.
`seed/procurement_sources.json` is the source registry (slug, level
state/county/local, platform, list_url, field map, documents). Generalized the
ingest runner into `run_ingest_adapter` (shared by SAM.gov + config sources).
Jobs: `validate_procurement_source.py` (live dry-run — prints extracted rows +
empty-field counts, the selector-tuning loop) and `ingest_procurement.py`
(`--slug` / `--all`). New dep `beautifulsoup4`.

**Status.** Framework + validator + fixture tests are done/green (57). The two
seeded GA/Bonfire configs are DRAFT (`active:false`) — selectors get tuned live
via the validator before going active (GPR is ASP.NET and may need POST/
Playwright). The pattern: adding a state/county/local source = a config entry +
a validate-and-tune pass.

**Code touched.** `app/adapters/solicitations/config_source.py` (new),
`app/ingest/solicitations.py`, `jobs/{validate_procurement_source,ingest_procurement}.py`
(new), `seed/procurement_sources.json` (new), `requirements.txt`, `INSTALL.md`,
`tests/test_procurement_config.py` (new).

**PRs.** Procurement-framework PR (this). Next: tune a first real source live
(GA GPR or a Bonfire/Ionwave agency) to active; document download/parse.

---

## 2026-06-09 — Inline PDF viewer for solicitation documents

**Context.** Plan/spec links downloaded the file; owner wanted to view in-app.

**What shipped.** `GET /api/documents/{doc_id}` — streams a stored
`solicitation_documents.url` back with `Content-Disposition: inline` so the
browser renders it (and the SAM.gov api_key is injected server-side, never
exposed). Bounded to URLs already in our DB (no open SSRF proxy). Drawer:
clicking a document toggles an inline `<iframe>` preview pane; "↗ new tab"
still opens it standalone. `SolicitationDocOut` now carries `id`.

**Code touched.** `app/api/documents.py` (new), `app/main.py`,
`app/schemas.py`, `app/api/solicitations.py`; `web/src/{api.ts,
SolicitationDrawer.tsx}`; `tests/test_app.py`. 54 tests green; web build clean.

**PRs.** Inline-PDF-viewer PR (this).

---

## 2026-06-09 — Web UI: Solicitations tab + detail drawer

**Context.** Solicitations had an API but no dashboard view.

**What shipped.** Tabbed UI (Projects | Solicitations). New `GET
/api/solicitations/{id}` detail endpoint (+ `SolicitationDetailOut`/`DocOut`
schemas) returning the solicitation + its attached documents. Web: refactored
the projects body into `ProjectsView`; added `SolicitationsView` +
`SolicitationsTable` (server-side sort on due date / value, has-docs + state
filters, paging) + `SolicitationDrawer` (fields, description, and **links to
the attached plan/spec PDFs**, source-portal link).

**Code touched.** `app/api/solicitations.py`, `app/schemas.py`; `web/src/`
(`App` now a tab shell; new `ProjectsView`, `SolicitationsView`,
`SolicitationsTable`, `SolicitationDrawer`; `api.ts`); `tests/test_app.py`.
53 tests green; web build clean.

**PRs.** Solicitations UI PR (this).

---

## 2026-06-09 — Bid/plans track: Solicitation foundation + SAM.gov adapter

**Context.** Product thesis expanded to rebuild PlanHub/ConstructConnect (not
just Shovels): aggregate **public bid-board solicitations + attached plan/spec
PDFs**. Owner confirmed PlanHub's content is publicly sourced, so it's the same
"long tail on a few platforms" pattern as permits.

**What shipped.** New `Solicitation` source family alongside permits:
- Schema: `solicitations` + `solicitation_documents` (seed/schema.sql +
  migration `2026-06-09-solicitations.sql`).
- `app/adapters/solicitations/`: `SolicitationAdapter` base + `NormalizedSolicitation`
  (stdlib), concrete **SAM.gov** adapter (federal Contract Opportunities JSON
  API, construction NAICS 236/237/238, `resourceLinks`→documents, paging +
  backoff), registry, and **registered scaffolds** for TX ESBD / FL VBS / GA
  GPR / BidNet / DemandStar (fail-safe `NotImplementedError` with entry URLs +
  access notes until live-validated).
- `app/ingest/solicitations.py` runner + `jobs/ingest_solicitations.py` CLI
  (idempotent upsert of solicitations + doc metadata; logs an IngestRun).
- API: `GET /api/solicitations` (filter by source/state/q/has_docs, sort by
  due date; graceful-empty). Signals registry gained `bid_due_soon`,
  `plans_available`, `pre_permit_stage`. `parse_date` now accepts ISO-8601 with
  tz offsets (SAM deadlines). New env `SAMGOV_API_KEY`.

**Code touched.** `app/adapters/solicitations/*` (new), `app/ingest/solicitations.py`,
`jobs/ingest_solicitations.py`, `app/api/solicitations.py`, `app/{config,main,schemas}.py`,
`app/adapters/base.py`, `app/signals/registry.py`, `seed/schema.sql` + migration,
docs. 52 tests green.

**PRs.** Roadmap (#181) + this foundation PR. Next: implement the scaffolded
state/national scrapers; PDF download/parse → signals.

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
