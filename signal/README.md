# sauce.ai / signal

Permit intelligence & distressed-project triage (PRD working name: "Bloodhound").

Continuously ingests **public building-permit data**, normalizes it into one
searchable project database, computes a catalog of **signals** — including
*derived* distress signals — and runs a daily **triage** that surfaces a
ranked "Call Today" list of commercial projects worth pursuing.

This is the **Phase 0 framework** (PRD §15). It runs as a container
(API + Postgres) deployable on Railway; see `INSTALL.md`.

> New here? Read `WARMUP.md` (paste-in session prompt) →
> `new-engineering-session-instructions.md` → `engineering-history.md`.

## What it does (target)

- Pulls permits per jurisdiction via a generic **Socrata/SODA adapter**
  (one adapter unlocks many cities), normalizing every source onto one
  canonical schema and keeping the raw payload for provenance.
- Dedups permits into **projects** (parcel/APN → address → permit number).
- Computes a **signal catalog** (ingested + derived). The derived tier —
  distress (stalled / expiring / stop-work / failed inspections / velocity),
  cabinet-relevance, value tier, category, geo, new-vs-known GC — is the IP.
- Scores each project against weighted **rules** → `lead_score` → flags
  "Call Today"; saved searches, daily digest, and one-click CRM push layer
  on top (later phases).

## Stack (PRD §14)

- **Backend:** Python + FastAPI; SQLAlchemy 2; `requests` for SODA.
- **DB:** PostgreSQL + PostGIS (geo) + pgvector (semantic) + `pg_trgm`.
- **Jobs:** standalone scripts under `jobs/`; APScheduler for the daily run.
- **Semantic:** Anthropic API for scope classification (cached on project).
- **Frontend:** React + Tailwind + TanStack Table (Vite), under `web/`.
- **Deploy:** Docker; Railway (`railway.json`); `docker-compose.yml` for local.

## Project layout

```
signal/
├── app/
│   ├── main.py              # FastAPI factory (create_app)
│   ├── config.py            # env-driven settings (stdlib only)
│   ├── db.py  models.py     # SQLAlchemy session + ORM
│   ├── schemas.py           # Pydantic I/O models
│   ├── api/                 # projects, jurisdictions, signals, health
│   ├── adapters/            # SourceAdapter base + socrata + paid stub + registry
│   ├── signals/             # registry (catalog) + derived + scoring
│   └── ingest/              # dedup + run orchestrator
├── jobs/                    # init_db, daily_ingest, scheduler
├── seed/
│   ├── schema.sql           # canonical schema (PostGIS + pgvector)
│   ├── jurisdictions.json   # seed metros + per-source field maps
│   └── migrations/          # incremental SQL (folded back into schema.sql)
├── web/                     # React + Tailwind SPA (Projects table)
├── tests/                   # pytest (pure-logic green w/o a DB)
├── Dockerfile  docker-compose.yml  railway.json  .env.example
└── INSTALL.md  README.md
```

## Running tests

```
python -m pytest signal/tests/ -q
```

The pure logic (adapters / signals / ingest dedup / scoring) runs green with
only `pytest` installed; the FastAPI/SQLAlchemy boot tests are gated on the
web stack being present (`pip install -r requirements-dev.txt`).
