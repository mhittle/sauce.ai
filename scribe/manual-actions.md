# sauce.ai/scribe — manual prod-action tracker

Outstanding actions that must be performed manually on prod (DB migrations,
env vars, Railway service setup, R2 rules). Anything in **Open** is
load-bearing for already-merged code. Each entry carries the **full
command/steps inline** and is also pasted into chat when shipped. Never write
real secret *values* here — document var names only.

> First-deploy note: scribe isn't deployed yet, so the Open items below are
> the **first-deploy bootstrap**. Once the owner runs them, move each to
> Completed with the date.

---

## Open

### MA-001 — Create the Railway project and three services
In Railway, create project `scribe` from the `mhittle/sauce.ai` repo with
services (each with **root directory `scribe`**):
- `scribe-api` — config-as-code path `scribe/apps/api/railway.json`
- `scribe-workers` — config-as-code path `scribe/apps/workers/railway.json`
- `scribe-web` — config-as-code path `scribe/apps/web/railway.json`; set
  build-time variable `VITE_API_URL` to the public URL of `scribe-api`

Add the **Postgres** and **Redis** plugins (plain PG16 is fine — no
extensions required).

### MA-002 — Set service env vars
Names only; values in the Railway UI (see `scribe/.env.example`):
- `scribe-api`: `DATABASE_URL`, `REDIS_URL`, `R2_ENDPOINT`,
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `SESSION_SECRET`
  (long random), `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `AUTH_ALLOWED_EMAILS` (comma-separated; first = admin),
  `API_PUBLIC_URL`, `WEB_PUBLIC_URL`, `NODE_ENV=production`
- `scribe-workers`: `DATABASE_URL`, `REDIS_URL`, `R2_*`,
  `ANTHROPIC_API_KEY`, `TAKEOFF_TOKEN_BUDGET=2000000`,
  `CRAWLER_DAILY_TOKEN_BUDGET=5000000`, optional `SAMGOV_API_KEY`,
  optional `SOCRATA_APP_TOKEN`, `NODE_ENV=production`

**`GOOGLE_CLIENT_ID` must be set on prod** — without it (and outside
production NODE_ENV) the API runs in dev-bypass auth.

### MA-003 — Create the Cloudflare R2 bucket
Create a private bucket (name = `R2_BUCKET`), generate an S3 API token
(access key + secret), and add a **90-day lifecycle delete rule scoped to
the `prospect-docs/` prefix** (PRD §9). `R2_ENDPOINT` is
`https://<account-id>.r2.cloudflarestorage.com`.

### MA-004 — Create the Google OAuth client
Google Cloud Console → Credentials → OAuth client (Web application):
- Authorized redirect URI: `https://<scribe-api domain>/auth/google/callback`
Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` on `scribe-api`.

### MA-005 — Run migrate + seed against prod
After the first `scribe-api` deploy (one-off shell on the api service, or
locally with prod `DATABASE_URL` + `AUTH_ALLOWED_EMAILS` exported):
```bash
node node_modules/@scribe/db/dist/migrate.js
node node_modules/@scribe/db/dist/seed.js
```
Seeds product lines (rates marked NEEDS REVIEW), pricing config v1, export
templates, org settings, Wave-1 crawler sources, and allowed users.

### MA-006 — Enter real pricing rates before the first external quote
Admin → Pricing Editor: replace every NEEDS REVIEW placeholder rate and save
(creates pricing config v2). Quotes pricing against NEEDS REVIEW rates are
blocked from `sent` by design (PRD §12).

### MA-007 — Validate seed Socrata field maps on first crawl
The three seeded jurisdiction field maps (SF / LA / NYC in `sources.config`)
are best-effort. Trigger each source once (Admin → Crawler Sources → Run
now), inspect `last_error` and a few inserted projects, and correct dataset
ids / column names in the source config via the admin UI.

### MA-008 — (Optional) SAM.gov API key
Request a free api.data.gov key for SAM.gov and set `SAMGOV_API_KEY` on
`scribe-workers`. Until set, the SAM.gov source records an error and skips.

---

## Completed

_None yet._
