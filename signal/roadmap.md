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
| Bonfire (Euna) CA opportunities adapter | 7 | 3 | ingest | done |
| Cal eProcure CSCR adapter (Playwright) | 6 | 6 | ingest | backlog |
| Portal scrapers (Accela/eTRAKiT/CityView) | 5 | 8 | ingest | backlog |
| Concrete paid-API adapter (e.g. Shovels.ai) | 4 | 4 | ingest | blocked |
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

### Bonfire (Euna) CA opportunities adapter
**Priority/LOE/Category/Status:** 7 / 3 / ingest / **done** (2026-06-30)
The requests-friendly California path. Many CA agencies post on Bonfire, which
exposes a public JSON list endpoint
(`<agency>.bonfirehub.com/PublicPortal/getOpenPublicOpportunitiesSectionData`)
— so one adapter (`adapters/solicitations/bonfire.py`, source_type `bonfire`)
lists open opportunities across many agencies with no key, no Playwright.
Ingest: `python jobs/ingest_solicitations.py --source bonfire`. Seeded agencies
ventura/wrd/calmhsa (verified live); add more subdomains in `DEFAULT_AGENCIES`
or via config `{"agencies": [...]}`. Limit: per-opportunity document pages are
Cloudflare-walled, so bid PDFs aren't bot-downloadable (discovery + triage now;
no scribe-connector docs from Bonfire). No NAICS → ingest all, let
`classify_solicitations` score cabinetry. This is the pragmatic answer to "add
CA like SAM.gov"; the statewide CSCR register below still needs Playwright.

### Cal eProcure CSCR adapter (Playwright)
**Priority/LOE/Category/Status:** 6 / 6 / ingest / backlog
California State Contracts Register — high-value CA bid source (~330 open
Posted events, construction included, each event carries downloadable bid
documents that feed the scribe quote connector). Registered as scaffold
`cscr` (`adapters/solicitations/scaffolds.py`), fails safe until built.

**Why it's not a config/`requests` source** (reverse-engineered 2026-06-30):
the public Event Search (`pages/Events-BS3/event-search.aspx`) is an **InFlight
NLX** SPA over Oracle **PeopleSoft**. The event grid loads via a *stateful*
POST to `…/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL`
carrying PeopleSoft state (`ICSID`/`ICStateNum`/`ICAction`) seeded by an
InFlight guest-session bootstrap (`InFlightSessionID` cookie). Confirmed: the
component GET 404s without the bootstrap, `?useAjax=1` returns only the SPA
shell, the criteria-form POST 400s. So it needs **Playwright** (headless
browser) — a new dependency + browser binaries in the Docker image.

**Build sketch:** Playwright loads the search page, waits for the grid, reads
rows (Event ID / Name / Department / End Date / Status), paginates, opens each
event for its document links, normalizes to `NormalizedSolicitation`. No NAICS
(CSCR uses UNSPSC/NIGP/CSI) → filter construction/cabinetry by keyword or lean
on `classify_solicitations`. Wire into `ingest_solicitations.py` (already
generic) and add a `validate_*`-style live check. Decision needed first:
accept Playwright in the signal image (size/memory/deploy).

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

## Done

- **Phase 0 — Skeleton framework** (PR: this PR, 2026-06-08).
- **Bonfire (Euna) CA opportunities adapter** (2026-06-30) — requests-only
  `bonfire` source listing open opportunities across CA agencies; the lighter
  alternative to the PeopleSoft-bound Cal eProcure/CSCR register.
