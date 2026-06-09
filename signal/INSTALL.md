# sauce.ai/signal — install & deploy

Phase 0 framework. Two paths: **local** (docker-compose) and **Railway**
(production target). Keep this file in sync with any change to
`app/config.py`, `app/db.py`, `jobs/*`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, or `railway.json` (see the engineering instructions).

---

## 1. Local development (docker-compose)

Brings up Postgres (PostGIS + pgvector) and the API.

```bash
cd signal
cp .env.example .env                      # optionally set SOCRATA_APP_TOKEN
docker compose up --build -d              # db + api
docker compose exec api python jobs/init_db.py   # schema + seed signals/metros/rule
```

- API: http://localhost:8000  (OpenAPI docs at `/docs`)
- Health: `GET /health`, `GET /health/db`

Run an ingest for one seed metro, then browse projects:

```bash
docker compose exec api python jobs/daily_ingest.py --slug chicago-il
curl 'http://localhost:8000/api/projects?signal=distress_stalled'
```

### Frontend (Vite dev server)

```bash
cd web
npm install
npm run dev            # http://localhost:5173, proxies /api -> :8000
```

### Running without Docker

You need a Postgres 15+ with PostGIS **and** pgvector installed. Then:

```bash
cd signal
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://signal:signal@localhost:5432/signal
python jobs/init_db.py
uvicorn app.main:app --reload
```

---

## 2. Railway (production target)

Railway builds from the `Dockerfile` (`railway.json` pins it) and injects
`$PORT`. Two services + a database:

1. **Database (needs PostGIS *and* pgvector).** Railway's default Postgres
   plugin ships neither, so use one of:
   - **Self-hosted image (recommended):** deploy `seed/docker-db/Dockerfile`
     as a service (set the service **Root Directory** to
     `signal/seed/docker-db`), add a **Volume** mounted at
     `/var/lib/postgresql/data`, and set `POSTGRES_USER/PASSWORD/DB`. The
     image bakes `PGDATA=/var/lib/postgresql/data/pgdata` — Railway volumes
     leave a `lost+found` at the mount root and `initdb` refuses a non-empty
     data dir, so it must init into a subdirectory (don't remove that ENV).
   - **External managed Postgres:** Neon/Supabase/Crunchy (all support both
     extensions); point `DATABASE_URL` at it. `jobs/init_db.py` runs the
     `CREATE EXTENSION` statements, but the binaries must exist on the plan.
2. **API service** — deploy this repo's `signal/` dir; set env vars from
   `.env.example`. Start command comes from `railway.json`
   (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`); health check `/health`.
3. **Worker/ingest** — either:
   - a separate Railway service running `python jobs/scheduler.py`
     (long-lived APScheduler), **or**
   - a Railway **cron** that runs `python jobs/daily_ingest.py` daily.
4. **Web (frontend)** — a separate service, **Root Directory `signal/web`**
   (builds `web/Dockerfile`: Vite build → nginx, SPA fallback, listens on
   `$PORT`). Set `VITE_API_BASE` to the API service's public URL — it's
   inlined at **build** time, so changing it requires a rebuild. The API's
   `CORS_ORIGINS` must allow the web origin (`*` works for now).

### Required env vars

| Var | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` (note the `+psycopg` driver). URL-encode `+ / = @ :` in the password, **or** leave unset and use the PG* vars below. |
| `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` | alternative to `DATABASE_URL`: set the password **raw** and the app encodes it (avoids "Could not parse SQLAlchemy URL" from special chars). |
| `SOCRATA_APP_TOKEN` | free token; lifts SODA rate limits |
| `SIGNAL_PAID_API_KEY` | leave unset to keep the paid adapter disabled |
| `ANTHROPIC_API_KEY` | semantic scope classification (optional Phase 0) |
| `FACILITY_LAT/LNG`, `SHIPPABLE_RADIUS_MI` | geo signals |
| `EMAIL_API_KEY`, `CRM_WEBHOOK_URL` | digest + CRM push (later phases) |
| `SECRET_KEY`, `CORS_ORIGINS` | web |

### First deploy

```
# after the API service is up and DATABASE_URL points at the DB:
railway run python jobs/init_db.py        # or run once via a one-off service
```

---

## 3. Migrations (migrate-after-deploy)

`seed/schema.sql` is the canonical full schema (idempotent). Incremental
changes go in `seed/migrations/YYYY-MM-DD-*.sql` and are **also folded back
into `schema.sql`**. App code must tolerate a not-yet-migrated table (the API
already degrades to empty rather than 500). Apply a migration after the code
that needs it is deployed; log it in `manual-actions.md`.

---

## 4. Known Phase-0 limits

- **Seed field maps are best-effort.** `seed/jurisdictions.json` field maps
  are derived from each portal's documented columns and must be validated on
  first pull; a bad map logs an error on the `IngestRun` rather than crashing.
- **No auth yet.** The API is open in Phase 0 (PRD §10 calls for simple
  internal auth — roadmap item).
- **Semantic classification is the rules baseline** until the Anthropic pass
  is wired (PRD §9); `cabinet_relevance`/`category`/`is_commercial` are
  keyword-derived for now.
- **Paid adapter is a stub** — disabled unless `SIGNAL_PAID_API_KEY` is set
  and a concrete client is implemented.
