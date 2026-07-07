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

### MA-006 — Deploy the web frontend (Railway service)
New Railway service from the repo, **Root Directory `signal/web`** (builds
`web/Dockerfile`). Set on that service:
```
VITE_API_BASE=<API service public URL, e.g. https://reliable-comfort-production-db32.up.railway.app>
```
`VITE_API_BASE` is inlined at build time (Vite), so changing it later requires
a redeploy/rebuild. Ensure the API's `CORS_ORIGINS` allows the web origin
(`*` is fine for now). Generate a public domain for the web service.

### MA-007 — Wire the scribe connector (shared service token)
The "quote in scribe" button on a solicitation's PDFs POSTs the PDF to scribe's
`/takeoffs`. It needs a shared secret on BOTH services:
```
# On the scribe API service:
SERVICE_TOKEN        = <random 32+ char string>
# On the signal API service (same value + scribe URLs):
SCRIBE_API_URL       = https://reliable-comfort-production-db32.up.railway.app   # scribe API origin
SCRIBE_SERVICE_TOKEN = <same value as scribe's SERVICE_TOKEN>
SCRIBE_WEB_URL       = https://scribe-web-production.up.railway.app              # for the deep link
```
NOTE: the example URLs above are placeholders — use scribe's actual API/web
public domains (NOT signal's). With the token unset on either side the button
returns 503 (connector disabled), which is the safe default. The token maps to
a single `signal-connector@scribe.local` estimator user created on first use.

### MA-008 — Purge natickma archive rows (data hygiene)
The `natickma` CivicPlus source ignored the Status=open filter and dumped the
town's full bid archive (689 rows, ~0 open) — a third of all solicitation
rows. The source is deactivated in `seed/procurement_sources.json`; purge the
already-ingested rows once on prod:
```sql
DELETE FROM solicitation_documents
 WHERE solicitation_id IN
   (SELECT id FROM solicitations WHERE source_type = 'natickma');
DELETE FROM solicitations WHERE source_type = 'natickma';
```

---

## Completed

_None yet._
