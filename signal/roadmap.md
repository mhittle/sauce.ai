# sauce.ai/signal — roadmap

Backlog for the permit-intelligence / triage tool, organized around the PRD's
build phases (§15). Each item: Priority (1–10, higher = sooner), LOE (1–10,
higher = more work), Category (`infra`, `ingest`, `signals`, `ui`, `backend`,
`algo`, `ops`, `security`, `docs`).

Status values: `backlog` · `in-progress` · `done` · `blocked`.

---

## At a glance

| Title | Pri | LOE | Cat | Status |
|---|---|---|---|---|
| Phase 0 — Skeleton framework | 10 | 7 | infra | done |
| §13 decisions — resolve open product calls | 10 | 1 | docs | in-progress |
| Validate seed jurisdiction field maps on first pull | 9 | 3 | ingest | backlog |
| First Railway deploy + managed Postgres (PostGIS/pgvector) | 9 | 4 | ops | backlog |
| Simple internal auth | 8 | 3 | security | backlog |
| Anthropic semantic scope classification | 8 | 5 | algo | backlog |
| Inspections ingestion (distress fuel) | 7 | 4 | ingest | backlog |
| Saved searches + scored-rule manager (API + UI) | 8 | 6 | backend | backlog |
| Daily email digest per rule profile | 7 | 4 | backend | backlog |
| Contractor cross-ref (the 2,000 contacts) | 7 | 4 | signals | backlog |
| Velocity-anomaly peer baselines | 6 | 5 | algo | backlog |
| Map view (PostGIS clustered pins + radius) | 6 | 5 | ui | backlog |
| ArcGIS adapter | 6 | 5 | ingest | backlog |
| Socrata catalog auto-discovery | 6 | 6 | ingest | backlog |
| CRM push (pluggable connector + first adapter) | 7 | 5 | backend | backlog |
| Coverage/freshness dashboard (UI) | 5 | 3 | ui | backlog |
| Portal scrapers (Accela/eTRAKiT/CityView) | 5 | 8 | ingest | backlog |
| Concrete paid-API adapter (e.g. Shovels.ai) | 4 | 4 | ingest | blocked |
| Bid/plans — Solicitation foundation + SAM.gov adapter | 9 | 6 | ingest | in-progress |
| Bid/plans — state platform adapters (TX/FL/GA) | 7 | 7 | ingest | backlog |
| Bid/plans — national aggregator adapters (BidNet/DemandStar) | 6 | 7 | ingest | backlog |
| Bid/plans — document store + PDF parse to signals | 7 | 7 | backend | backlog |
| Enrichment signals (liens/litigation/news) | 4 | 8 | signals | backlog |
| Autonomous agent fleet for signal | 3 | 7 | ops | backlog |

---

## Items in detail

### Phase 0 — Skeleton framework
**Priority/LOE/Category/Status:** 10 / 7 / infra / done (PR: this PR, 2026-06-08)
Schema + generic Socrata adapter + seed metros + signal registry + ingest
pipeline + scoring + FastAPI projects API + minimal React table + engineering
system docs. See `engineering-history.md` 2026-06-08.

### §13 decisions — resolve open product calls
**Priority/LOE/Category/Status:** 10 / 1 / docs / in-progress
The PRD flags six decisions that shape the build path. Track answers here:
1. **CRM target** (determines the first connector) — _open_.
2. **Free-vs-paid coverage** (strictly free Socrata, or pay for a permit API
   to accelerate national coverage) — _open_; Phase 0 ships free + a disabled
   paid stub.
3. **Seed metros** (definitive 5–10) — _provisional_: Chicago, NYC, LA,
   Austin, Seattle, SF, Dallas (largest commercial Socrata markets).
4. **Shippable radius** (true national vs distance-weighted) — _open_; default
   500 mi from facility, configurable via env.
5. **The 2,000 contacts** export format for the new-GC cross-ref — _open_.
6. **Hosting/infra accounts** (DB, email sender) — _open_; targeting Railway +
   managed Postgres.

### Validate seed jurisdiction field maps on first pull
**Priority/LOE/Category/Status:** 9 / 3 / ingest / backlog
Field maps in `seed/jurisdictions.json` are best-effort. Run each seed metro
once, inspect the `IngestRun` error + sample normalized rows, and correct the
map (column names, geocode location, status/expiration fields). Add a small
`jobs/validate_jurisdiction.py` that dry-runs one page and reports unmapped /
empty canonical fields.

### First Railway deploy + managed Postgres (PostGIS/pgvector)
**Priority/LOE/Category/Status:** 9 / 4 / ops / backlog
Provision the DB (must have PostGIS *and* pgvector — see
`engineering-history.md` Load-bearing state), set env vars, run
`jobs/init_db.py`, deploy the API + an ingest worker/cron. See `INSTALL.md` §2.
First-deploy steps are queued in `manual-actions.md`.

### Simple internal auth
**Priority/LOE/Category/Status:** 8 / 3 / security / backlog
PRD §10: internal multi-user login (Mike / marketing assistant / inside sales).
`users` table exists; add password auth + session/JWT + route guards. The API
is currently open.

### Anthropic semantic scope classification
**Priority/LOE/Category/Status:** 8 / 5 / algo / backlog
PRD §9: classify `work_description` via the Anthropic API returning
`{is_commercial, category, cabinet_relevance, distress_flags, one_line_summary}`,
cache on `projects.scope_summary`/`scope_embedding`, only re-run on text
change. Overrides the rules baseline in `signals/derived.py`. Optional pgvector
semantic filter. Keep it in jobs (never on the request path).

### Inspections ingestion (distress fuel)
**Priority/LOE/Category/Status:** 7 / 4 / ingest / backlog
`inspections` table + `distress_inspections` signal exist, but no adapter pulls
inspection datasets yet. Add inspection field maps per jurisdiction (often a
separate Socrata dataset) and wire into the run.

### Saved searches + scored-rule manager (API + UI)
**Priority/LOE/Category/Status:** 8 / 6 / backend / backlog
PRD §9/§10: CRUD for saved searches and weighted rules (multiple profiles),
threshold flagging, digest assignment. Scoring engine + `rules`/`saved_searches`
tables exist; needs API endpoints + a UI manager.

### Daily email digest per rule profile
**Priority/LOE/Category/Status:** 7 / 4 / backend / backlog
PRD §11: top-N flagged projects grouped by rule, "why flagged" line, quick
actions, configurable recipients/send time. `digests` table + transactional
sender (Resend/Postmark/SendGrid via `EMAIL_API_KEY`).

### Contractor cross-ref (the 2,000 contacts)
**Priority/LOE/Category/Status:** 7 / 4 / signals / backlog
Import the known-contacts export into `contractors` (`in_crm=true`), wire
`known_gc`/`new_gc`/`repeat_gc_count` off it (the derived functions already
accept a known-contractor set). Blocked on §13.5 export format.

### Velocity-anomaly peer baselines
**Priority/LOE/Category/Status:** 6 / 5 / algo / backlog
`distress_velocity` needs per-type/size/region median durations. Compute
rolling baselines in a job and feed `peer_median_active_days`.

### Map view (PostGIS clustered pins + radius)
**Priority/LOE/Category/Status:** 6 / 5 / ui / backlog
PRD §10: Mapbox/Leaflet map, clustered pins, radius-from-facility filter
(PostGIS `ST_DWithin`). Add a `/api/projects/geojson` endpoint.

### ArcGIS adapter
**Priority/LOE/Category/Status:** 6 / 5 / ingest / backlog
PRD §6.2: generic REST query against ArcGIS Feature Services. Register under
`source_type=arcgis` in the adapter registry; reuse `normalize_record`.

### Socrata catalog auto-discovery
**Priority/LOE/Category/Status:** 6 / 6 / ingest / backlog
PRD §6.1: discover permit datasets across Socrata domains to scale to 1000+
cities. Auto-propose jurisdiction rows (with a draft field_map) for review.

### CRM push (pluggable connector + first adapter)
**Priority/LOE/Category/Status:** 7 / 5 / backend / backlog
PRD §12: generic webhook connector + one concrete CRM adapter (§13.1). Map
project→deal, contractor→contact/company, why-flagged+scope→notes; dedupe and
store `crm_id` back. Blocked on §13.1 CRM choice.

### Coverage/freshness dashboard (UI)
**Priority/LOE/Category/Status:** 5 / 3 / ui / backlog
PRD §10: surface `/api/jurisdictions` (live cities, last good pull, staleness)
as a UI page.

### Portal scrapers (Accela/eTRAKiT/CityView)
**Priority/LOE/Category/Status:** 5 / 8 / ingest / backlog
PRD §6.3: per-vendor scraper templates for gap jurisdictions (public records;
respect ToS/robots/rate limits; no CAPTCHA bypass). Register as new
`source_type`s.

### Concrete paid-API adapter (e.g. Shovels.ai)
**Priority/LOE/Category/Status:** 4 / 4 / ingest / blocked
Implement the real client behind the existing `PaidApiAdapter` stub. Blocked on
§13.2 (free-vs-paid decision) + an account/key.

### Enrichment signals (liens/litigation/news)
**Priority/LOE/Category/Status:** 4 / 8 / signals / backlog
PRD §8C/§15 Phase 4: external enrichment + contact resolution + dedup
hardening. Facets already pre-defined in the registry (enrichment tier).

### Autonomous agent fleet for signal
**Priority/LOE/Category/Status:** 3 / 7 / ops / backlog
Optionally mirror news's unattended agent fleet (dev/QA/PM/post-deploy) for
signal once the product is established. Deliberately deferred — signal ships
with just CI (`signal-ci.yml`) for now.

---

## Data-acquisition strategy (the "rebuild Shovels + PlanHub" plan)

The product thesis is to recreate Shovels.ai (permit aggregation) **and**
PlanHub/ConstructConnect (project + plans) entirely from **publicly accessible
sources**. Both are the same architectural pattern as our permit work: a long
tail of jurisdictions/agencies concentrated on a handful of platforms, each
unlocked by a generic adapter behind the `SourceAdapter` interface. Two tracks:

**Track A — Permits (Shovels model):** scale the existing permit ingestion —
ArcGIS adapter → Socrata auto-discovery → portal scrapers (Accela/eTRAKiT/
CityView) → contractor + inspections datasets → paid gap-fill. (Items above.)

**Track B — Bids & plans (PlanHub model):** public procurement / bid boards
post commercial construction solicitations **with plan + spec PDFs attached**.
A new `Solicitation` entity + `solicitation_documents` store sits alongside
Permit/Project; documents get parsed (text → the LLM scope pass) and feed the
same signal engine. Permits catch a project at approval (+ distress);
solicitations catch it **pre-construction, with plans**. Together = the full
ConstructConnect/PlanHub picture. Compliance per PRD §16 (ToS/robots/rate
limits, no CAPTCHA bypass; some portals require free registration — respect it).

### Bid/plans — Solicitation foundation + SAM.gov adapter
**Priority/LOE/Category/Status:** 9 / 6 / ingest / in-progress
The "Socrata moment" for the PlanHub side. Add the `Solicitation` +
`solicitation_documents` schema, a `SolicitationAdapter` base + registry, the
new signals (`bid_due_soon`, `plans_available`, `pre_permit_stage`), and a
concrete **SAM.gov** adapter (federal Contract Opportunities — clean public
JSON API at `api.sam.gov/prod/opportunities/v2/search`, `api_key` query param,
construction NAICS 236/237/238, `resourceLinks` = attachments). Job:
`jobs/ingest_solicitations.py`. Needs env `SAMGOV_API_KEY` (free from
SAM.gov/data.gov). Proves the end-to-end solicitation pipeline.

### Bid/plans — state platform adapters (TX/FL/GA)
**Priority/LOE/Category/Status:** 7 / 7 / ingest / backlog
Concrete adapters for three public state systems (scaffolded + registered now,
need live validation): **Texas ESBD** (`txsmartbuy.gov/esbd`, no login),
**Florida VBS/MFMP** (vendor bid system, public), **Georgia GPR**
(`ssl.doas.state.ga.us/gpr`, state + local public-works ≥ $100k; ties to the
Atlanta facility). Mostly HTML — likely needs `requests`+parser or Playwright;
respect ToS/robots.

### Bid/plans — national aggregator adapters (BidNet/DemandStar)
**Priority/LOE/Category/Status:** 6 / 7 / ingest / backlog
Private platforms aggregating thousands of public agencies nationally
(scaffolded + registered now): **BidNet Direct** (`bidnetdirect.com/
solicitations/open-bids`) and **DemandStar** (`demandstar.com/browse-bids`).
Public listings are browsable; full solicitation docs are partly gated behind
free registration / paid tiers — capture what's publicly available, respect
ToS. Each platform covers many agencies → high coverage per adapter.

### Bid/plans — document store + PDF parse to signals
**Priority/LOE/Category/Status:** 7 / 7 / backend / backlog
Download attached plan/spec PDFs to object storage (metadata + links in
`solicitation_documents`), extract text, and feed the LLM scope pass so
cabinet-relevance/category/value-tier compute off the **actual drawings/specs**
(richer than a permit's one-line description). Heavy PDFs → storage + OCR +
anti-bot care.

---

## Done

- **Phase 0 — Skeleton framework** (PR: this PR, 2026-06-08).
