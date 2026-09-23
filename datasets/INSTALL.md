# sauce.ai/datasets — install & deploy

One container (FastAPI API + UI + crawl threads) and one persistent volume
(`/data`: SQLite catalog + downloaded files). No database service.

**Run exactly one replica.** The catalog is a SQLite file and crawls run as
threads in the API process; two replicas would split the catalog and the
crawl state.

---

## 1. Local (5 minutes)

```bash
cd datasets
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests -q                 # expect all green, no key needed
export ANTHROPIC_API_KEY=sk-ant-...       # omit to run search-only
uvicorn app.main:app --reload             # http://localhost:8000
```

Or with Docker:

```bash
docker build -t sauce-datasets datasets
docker run -p 8000:8000 -v "$PWD/datasets/data:/data" -e ANTHROPIC_API_KEY sauce-datasets
```

---

## 2. Railway (production)

1. **New service.** Railway → your sauce.ai project → **+ New** → **GitHub
   Repo** → `mhittle/sauce.ai`.
2. **Root directory.** Service → **Settings** → **Source** → *Root Directory*
   = `datasets`. Railway then picks up `datasets/railway.json` (Dockerfile
   build, `/health` healthcheck, start command). Optionally set *Watch Paths*
   to `datasets/**` so news/signal/scribe pushes don't redeploy it.
3. **Volume.** Service → right-click / **+ New** → **Volume** → mount path
   `/data`. Size: start at 5–10 GB; downloads are capped at
   `DATASETS_MAX_DOWNLOAD_MB` (500) per file, 10 files per dataset.
4. **Variables.** Service → **Variables**:

   | Variable | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | your key (console.anthropic.com → API keys) |
   | `DATASETS_DATA_DIR` | `/data` (already the image default; set it anyway) |
   | `DATASETS_MAX_CONCURRENT_CRAWLS` | `1` to start (cost control) |

   Everything else has defaults; see `.env.example` (model, effort, crawl
   length, swarm size, download caps).
5. **Keep it awake.** Settings → *Serverless / App Sleeping* **off**. A
   sleeping container kills in-flight crawls (they're marked `interrupted`
   on the next boot).
6. **Replicas = 1** (Settings → Deploy). See the note at the top.
7. **Domain.** Settings → Networking → **Generate Domain** (or add a custom
   domain, e.g. `datasets.sauce.ai`, and point a CNAME at it).
8. **Deploy & verify.**
   ```bash
   curl https://<domain>/health
   # {"status":"ok","llm_configured":true,"active_crawls":[]}
   ```
   `llm_configured: false` means the key isn't set on this service.

---

## 3. First crawl (do this supervised)

The agent loop has only been tested against a scripted client, so watch the
first real run:

1. Open `https://<domain>/`, search `pneumothorax`. A 10-minute crawl starts;
   the panel shows the agents' log and cards appear as they're recorded.
2. Check the **Crawls** tab: status `done`, hits > 0, and the token counts.
   Token counts × model price ≈ cost of that crawl; extrapolate before
   enabling the 1-hour crawl.
3. If it fails, the error is on the crawl row and in Railway → Deployments →
   Logs (`crawl N failed ...`).
4. Only then try **Run 1-hour crawl**.

---

## 4. Schedule the nightly crawl

Railway volumes attach to a single service, so a separate Railway cron
service can't reach the catalog. Trigger the running API instead — e.g. a
GitHub Actions schedule in `.github/workflows/datasets-crawl.yml`:

```yaml
name: datasets-nightly-crawl
on:
  schedule: [{ cron: "0 9 * * *" }]   # 09:00 UTC ≈ 02:00 PT
  workflow_dispatch:
jobs:
  crawl:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -fsS -X POST "${{ vars.DATASETS_URL }}/api/crawls" \
            -H 'Content-Type: application/json' -d '{"mode":"broad","minutes":60}'
```

Set repo variable `DATASETS_URL=https://<domain>`. On a plain VM instead of
Railway, use cron with the CLI:
`0 2 * * * cd /app && python -m jobs.crawl >> /data/crawl.log 2>&1`.

---

## 5. Before sharing the URL

There is no auth: anyone with the URL can start paid crawls. Until the
sauce.ai account layer is wired in, either keep the domain private or put
it behind an access proxy (e.g. Cloudflare Access), and keep
`DATASETS_MAX_CONCURRENT_CRAWLS=1`. Set a monthly spend limit in the
Anthropic console.

---

## 6. Operations

- **Backup:** the whole state is `/data` (`catalog.sqlite3` + `files/`).
  Snapshot the volume, or `sqlite3 /data/catalog.sqlite3 ".backup /data/bk.sqlite3"`.
- **Recount 510(k)s:** `POST /api/conditions/<name>/refresh-510k`.
- **Retry a dataset's downloads:** `POST /api/datasets/<id>/download`.
- **Stop a crawl:** Crawls tab → Stop, or `POST /api/crawls/<id>/cancel`.
- **Note:** the repo-wide FTP deploy (`.github/workflows/main.yml`) also
  copies `datasets/` source to the GoDaddy host, as it does `signal/`. It is
  not executed there.
