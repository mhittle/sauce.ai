# sauce.ai/scribe — manual prod-action tracker

Outstanding actions that must be performed manually on prod (DB migrations,
env vars, Railway service setup, storage rules). Anything in **Open** is
load-bearing for already-merged code. Each entry carries the **full
command/steps inline** and is also pasted into chat when shipped. Never write
real secret *values* here — document var names only.

---

## Open

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

### MA-010 — (Optional) OpenAI key for AI cross-validation
The "AI Cross Validation" toggle (Admin → Branding & Freight) is off by
default and is a no-op until `OPENAI_API_KEY` is set on `scribe-workers`.
Optionally set `OPENAI_VISION_MODEL` (default `gpt-4.1`). With the key set and
the toggle on, each takeoff page is also extracted by OpenAI and disagreements
lower the primary (Anthropic) line confidence for review. Anthropic remains
the source of truth; OpenAI failures are logged, never fatal.

### MA-009 — MinIO lifecycle rule for prospect-docs/
The MinIO console build lacked the Lifecycle settings page, so the 90-day
expiry on crawler-downloaded docs (PRD §9) is not set. From any machine with
`mc` (read creds from the Railway MinIO service variables — never paste them
into chat):
```bash
mc alias set scribe https://<minio S3 API domain> <access key> <secret>
mc ilm rule add scribe/scribe --expire-days 90 --prefix "prospect-docs/"
mc ilm rule ls scribe/scribe
```
Until done, prospected PDFs accumulate on the volume (takeoffs/quotes are
unaffected — they are not meant to expire).

---

## Completed

### 2026-06-12 — first production deploy (MA-001 … MA-005)
- **MA-001** Railway project created from the GitHub repo: `scribe-api`
  (https://scribe-api-production-757c.up.railway.app), `scribe-web`
  (https://scribe-web-production.up.railway.app), `scribe-workers`, plus
  Postgres and Redis plugins. All services root dir `scribe`, branch `main`.
- **MA-002** Service env vars set; storage creds as project **shared
  variables** (`R2_*`) referenced by api + workers; `VITE_API_URL` build-time
  on web.
- **MA-003** MinIO template service + volume; bucket `scribe`; S3 API on the
  port-9000 public domain. Lifecycle rule deferred to **MA-009**.
- **MA-004** Google OAuth client created. Gotcha hit: the redirect URI must
  be the FULL `https://<api domain>/auth/google/callback` path — a bare
  domain causes `redirect_uri_mismatch`.
- **MA-005** Boot migrate + seed (#196) verified on prod: schema applied,
  product lines/templates/sources/users seeded, `/health/db` green.

Original step-by-step details preserved in `INSTALL.md` §2.
