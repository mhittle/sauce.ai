# sauce.ai/signal — manual prod-action tracker

Outstanding actions that must be performed manually on prod (DB migrations,
env vars, enabling DB extensions, cron entries). Anything in **Open** is
load-bearing for already-merged code. Each entry carries the **full
command/SQL inline** (a path alone is not acceptable) and is also pasted into
chat when shipped. Never write real secret *values* here — document var names.

> Phase 0 note: signal isn't deployed yet, so the Open items below are the
> **first-deploy bootstrap**. Once an owner runs them, move each to Completed
> with the date. Railway-provided values (DATABASE_URL, etc.) are placeholders
> until the project exists.

---

## Open

### MA-001 — Provision managed Postgres with PostGIS + pgvector
The DB backing prod MUST have both PostGIS and pgvector (schema.sql creates
them). Railway's bundled Postgres may lack one; deploy `seed/docker-db/`
(image bundles both) or use Neon/Supabase/Crunchy.
On Railway with a Volume, mount it at `/var/lib/postgresql/data`; the image
sets `PGDATA=/var/lib/postgresql/data/pgdata` so initdb skips the volume's
`lost+found` (otherwise: `initdb: error: directory ... exists but is not
empty` crash-loop).
Verify after provisioning:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SELECT postgis_version();          -- should return a version
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

### MA-002 — Set API service env vars on Railway
Set these on the API service (names only; supply values in the Railway UI).
For the DB connection use EITHER DATABASE_URL (URL-encode +,/,=,@,: in the
password) OR the discrete PG* vars (password raw — the app encodes it; avoids
"Could not parse SQLAlchemy URL"):
```
DATABASE_URL   = postgresql+psycopg://<user>:<encoded-pass>@<host>:<port>/<db>
# --- or, instead of DATABASE_URL: ---
# PGHOST=<host>  PGPORT=<port>  PGUSER=signal  PGPASSWORD=<raw>  PGDATABASE=signal
SOCRATA_APP_TOKEN = <free token from any Socrata portal's API page>
SECRET_KEY     = <random 32+ char string>
CORS_ORIGINS   = <frontend origin, or * for now>
FACILITY_LAT   = <facility latitude>
FACILITY_LNG   = <facility longitude>
SHIPPABLE_RADIUS_MI = 500
# optional / later phases: ANTHROPIC_API_KEY, EMAIL_API_KEY, CRM_WEBHOOK_URL
# leave SIGNAL_PAID_API_KEY UNSET to keep the paid adapter disabled
```
Note the `+psycopg` in DATABASE_URL — a bare `postgres://` will fail.

### MA-003 — Initialize the schema + seed data (run once after API is up)
```bash
railway run python jobs/init_db.py
# applies seed/schema.sql, seeds signal_catalog from the registry,
# loads seed/jurisdictions.json, and creates the default triage rule.
```

### MA-004 — Schedule the daily ingest
Either run a long-lived worker service:
```bash
python jobs/scheduler.py        # APScheduler; INGEST_HOUR_UTC controls time
```
or add a Railway cron (recommended) running daily:
```bash
python jobs/daily_ingest.py
```

### MA-005 — Validate seed jurisdiction field maps (after first ingest)
Run one metro and inspect results before trusting the data:
```bash
railway run python jobs/daily_ingest.py --slug chicago-il
# then check the ingest_runs row + a few permits for unmapped/empty fields;
# correct seed/jurisdictions.json field maps and re-run as needed.
```

---

## Completed

_None yet._
