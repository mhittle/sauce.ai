# sauce.ai/phenotype — install & deploy

A single FastAPI service + SQLite file. No external database. Same container
pattern as `redteam/` and `signal/`.

## Local

```
cd phenotype
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -q
cp .env.example .env            # set ANTHROPIC_API_KEY at minimum
uvicorn app.main:get_app --factory --reload
```

Open http://localhost:8000.

## Configuration

All via environment variables (see `.env.example`); defaults in
`app/config.py`.

- **`ANTHROPIC_API_KEY`** (required for real jobs). Screening uses
  `PHENOTYPE_SCREEN_MODEL` (default `anthropic:claude-sonnet-5`), extraction
  `PHENOTYPE_EXTRACT_MODEL` (default `anthropic:claude-opus-5`). A default job
  (150 records, 25 papers) makes roughly 15 screening calls and 25 extraction
  calls.
- **Literature APIs** are free and keyless. Set `PHENOTYPE_CONTACT_EMAIL`
  (NCBI etiquette) and optionally `NCBI_API_KEY` (3 → 10 requests/s).
  Responses are cached in SQLite for `PHENOTYPE_HTTP_CACHE_TTL_S` (7 days).
- **Email**: set `SMTP_HOST` (+ `SMTP_USER`/`SMTP_PASS`). Without it the
  report stays at `/jobs/<id>`.
- `PUBLIC_BASE_URL`: externally reachable base, used in the email link.

## Container / Railway

```
docker build -t phenotype .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -v $PWD/data:/app/data phenotype
```

`railway.json` builds the Dockerfile and health-checks `/health`. Mount a
volume at `/app/data` so jobs and the HTTP cache survive restarts.

**Routing.** Production is Railway at `https://phenotype.sauce.ai` (see
`manual-actions.md`). The form uses relative URLs, so it also works behind a
path prefix with a trailing slash if the proxy strips the prefix.

## Operational notes

- Jobs hold no secrets; on restart, queued/running jobs are re-run from the
  start (`JobQueue.recover`). The queue is in-process: run one replica.
- Per-IP rate limit `PHENOTYPE_JOBS_PER_HOUR_PER_IP` (default 6).
- `GET /health` → `{"ok": true}`; `GET /config` returns the vocabularies the
  form renders.
