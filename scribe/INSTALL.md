# sauce.ai/scribe — install & deploy

Two paths: **local** dev and **Railway** (production target). Keep this file
in sync with any change to `apps/*/Dockerfile`, `apps/*/railway.json`,
`packages/db/migrations/`, root `package.json` scripts, or `.env.example`
(see the engineering instructions).

---

## 1. Local development

Prereqs: Node 22, pnpm 10 (corepack), Postgres 16, Redis.

```bash
cd scribe
cp .env.example .env            # fill in DATABASE_URL, REDIS_URL; the rest is optional locally
pnpm install
pnpm build
pnpm db:migrate && pnpm db:seed # schema + product lines/templates/sources/users
```

Run the three services (each reads `.env` via your shell or a tool like
`dotenv`; the apps read plain process env):

```bash
# API (http://localhost:3001)
cd apps/api && node dist/server.js

# Workers (needs ANTHROPIC_API_KEY for extraction; R2_* for object storage)
cd apps/workers && node dist/index.js

# Web (http://localhost:5173, dev server proxies nothing — set VITE_API_URL)
cd apps/web && pnpm dev
```

- Health: `GET /health`, `GET /health/db`.
- **Dev auth bypass:** with `GOOGLE_CLIENT_ID` unset and
  `NODE_ENV != production`, every request authenticates as a local admin
  (`dev@scribe.local`). Set real Google OAuth credentials to test the login
  flow.
- Tests and the eval suite need no DB/network: `pnpm test`, `pnpm eval`.

### What needs external services

| Feature | Needs |
|---|---|
| Upload + takeoff extraction | R2_* (object storage), ANTHROPIC_API_KEY, Redis, workers running |
| Spreadsheet intake (deterministic path) | R2_* + Redis only (model assist optional) |
| Crawler (Socrata) | nothing extra (SOCRATA_APP_TOKEN recommended) |
| Crawler (SAM.gov) | SAMGOV_API_KEY (free at sam.gov) |
| Quote PDF | R2_* |
| BigCommerce draft orders | BIGCOMMERCE_* (stubbed — returns 501 with explanation) |

## 2. Railway deploy (everything runs on Railway)

Three services from this repo + Postgres + Redis + a MinIO service for
object storage. **Every repo service sets its root directory to `scribe`**
so the Docker build context is the monorepo root.

| Service | Settings |
|---|---|
| `scribe-api` | Root dir `scribe`; config path `scribe/apps/api/railway.json` (Dockerfile `apps/api/Dockerfile`); healthcheck `/health` |
| `scribe-workers` | Root dir `scribe`; config path `scribe/apps/workers/railway.json` |
| `scribe-web` | Root dir `scribe`; config path `scribe/apps/web/railway.json`; build-time var `VITE_API_URL` = public URL of scribe-api |
| Postgres | Railway Postgres plugin (no extensions needed — plain PG16 works) |
| Redis | Railway Redis plugin |
| MinIO | Railway MinIO template + attached volume; public domain on the S3 API port. `R2_ENDPOINT` = that URL, keys = MinIO root user/service account, bucket `scribe`. Path-style addressing is the storage package's default. |

Env vars (names only — values in the Railway UI; see `.env.example` for the
full list):

- **api:** `DATABASE_URL`, `REDIS_URL`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `SESSION_SECRET`, `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `AUTH_ALLOWED_EMAILS`, `API_PUBLIC_URL`,
  `WEB_PUBLIC_URL`, `NODE_ENV=production`
- **workers:** `DATABASE_URL`, `REDIS_URL`, `R2_*`, `ANTHROPIC_API_KEY`,
  `TAKEOFF_TOKEN_BUDGET`, `CRAWLER_DAILY_TOKEN_BUDGET`, `SAMGOV_API_KEY`
  (optional), `SOCRATA_APP_TOKEN` (optional), `NODE_ENV=production`
- **web:** `VITE_API_URL` (build-time)

First-deploy bootstrap: **none** — the api runs migrations + seed on boot
(idempotent, advisory-locked; `SKIP_BOOT_MIGRATIONS=1` opts out). Check the
api deploy logs for `migrations applied: …` / `seed ensured`. The seed reads
`AUTH_ALLOWED_EMAILS` from the api service env (first email = admin), so set
it before the first boot.

Google OAuth: create an OAuth client (web application) in Google Cloud
Console with redirect URI `https://<api domain>/auth/google/callback`; put
the allowed sign-in emails in `AUTH_ALLOWED_EMAILS` (first email becomes
admin) before seeding, or add users later via Admin → Users.

Object storage: create the private `scribe` bucket in the MinIO console,
then add the 90-day lifecycle rule on the `prospect-docs/` prefix (PRD §9)
with the `mc` CLI:

```bash
mc alias set scribe https://<minio domain> <access key> <secret>
mc ilm rule add scribe/scribe --expire-days 90 --prefix "prospect-docs/"
```

(Cloudflare R2 or AWS S3 also work — the storage package is generic
S3-compatible; set `S3_FORCE_PATH_STYLE=0` only if a provider requires
virtual-hosted-style URLs.)

## 3. Migrations

Migrations are tracked in `_migrations` and applied in filename order on api
boot (and by `pnpm db:migrate` locally); both paths are idempotent. New
migrations go in `packages/db/migrations/NNNN_name.sql` (never edit applied
files) — they apply automatically on the deploy that ships them. A failed
migration fails the prod deploy by design.

## 4. Known v1 limits

- **Seeded pricing rates are placeholders** marked NEEDS REVIEW; quotes that
  price against them cannot be sent. Enter real rates in Admin → Pricing
  Editor first.
- **PDF extraction pipeline is built but not yet validated on live plan
  sets** — first real takeoffs should be reviewed closely; the eval corpus
  starts from them.
- **No OCR fallback yet** for scan-only PDFs (roadmap).
- **Sheet-index classification shortcut not implemented** — all pages get
  thumbnail classification (still ~25 low-res calls for a 200-page set).
- **BigCommerce draft orders stubbed** (501).
- **bull-board and Sentry not wired yet** (roadmap; pino logs are in).
- **"Send" drafts a mailto** — the rep attaches the generated PDF manually
  (mailto cannot attach files); automated email drafting is on the roadmap.
