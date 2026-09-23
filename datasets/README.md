# sauce.ai / datasets

LLM-driven finder for medical datasets — the first building block of a
"Hugging Face for health data" (working name disease.ai). You type a target
("MS brain MRI with contrast and clinical labels", "pneumothorax"); the app
shows everything it has already indexed, then launches a swarm of Claude
agents that crawl the web for more, adding cards to the results as they're
found. Everything found is kept in a local catalog, so later searches (and the
Directory) return it instantly — the web crawl is memoized per query.

Scope of this first push: **discovery + flat files**. ETL, ingestion, and a
real database are later.

## What it does

| | |
|---|---|
| **Search** | Full-text search over the catalog (SQLite FTS5), widened by synonyms of any condition the query names and by datasets earlier crawls of the same query found. Then, unless the same query was crawled in the last `DATASETS_RECRAWL_HOURS` (24), it launches a crawl (default 10 min) and streams new cards in. "Crawl again" forces a new one. |
| **Directory** | Every condition, ranked by FDA 510(k) clearances, with dataset / open / downloaded counts. Click a row for its datasets. |
| **Run 1-hour crawl** | Broad crawl: walks conditions in 510(k) order (seeded from `seed/conditions.json`, plus any condition found since), running a planned swarm per condition until the hour is up. The same thing runs from cron via `python -m jobs.crawl`. |
| **Dataset cards** | Title, source, access type (open / free registration / credentialed / DUA / by request), conditions, modalities, labels, size, subjects, formats, license, citation, **access instructions**, direct links, and links to files we collected. |
| **Downloads** | For open-access datasets, direct flat-file links (csv/tsv/json/parquet/xlsx/zip/tar.gz/nii.gz/edf/dcm/h5/…) are downloaded to `data/files/<dataset-id>/` (size-capped, sha256 recorded) and served at `/files/<id>`. Anything behind a login/DUA is marked *Manual access* with instructions. |

## How a crawl works

```
query ─▶ planner (1 structured-output call)
           ├─ canonical conditions + synonyms + FDA device-name terms ─▶ openFDA 510(k) count
           └─ N search "angles" (PhysioNet, TCIA, OpenNeuro, challenges, Kaggle, Zenodo, …)
                 │
                 ▼  N agents in parallel (manual tool-use loop, one per angle)
          tools: web_search, web_fetch (Anthropic server tools)
                 record_dataset  → upsert card (dedup on canonical landing URL, fields merged)
                 check_catalog   → what we already have
                 probe_url       → is this link a real file or a login page?
                 │
                 ▼  each recorded dataset → background download pool (open access only)
```

- Model: `claude-opus-5` (configurable), adaptive thinking, automatic prompt
  caching, server-side refusal fallback (`fallbacks: "default"`).
- Planner runs at effort `high`; crawl agents at `medium` (the bulk of spend).
- Bounded by wall clock: agents check the deadline between turns; each agent
  also has a turn cap (`DATASETS_MAX_TURNS`). Token usage is recorded per crawl
  (Crawls tab).

## Layout

```
datasets/
├── app/
│   ├── main.py       FastAPI app + routes (search, crawls, directory, files, UI)
│   ├── crawler.py    planner, agent loop, tools, swarm, broad crawl
│   ├── manager.py    background crawl threads, cancel, download pool
│   ├── store.py      SQLite catalog (datasets, files, conditions, crawls, FTS5)
│   ├── fda.py        openFDA 510(k) counts
│   ├── download.py   flat-file downloader + URL probe (SSRF-guarded)
│   ├── config.py     env settings
│   └── static/       single-page UI (no build step)
├── jobs/crawl.py     CLI for cron: one crawl in the foreground
├── seed/conditions.json   starting condition list for broad crawls
└── tests/            pytest, no network or API key needed
```

## Run it

```
cd datasets
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=...            # without it: search works, crawling is off
uvicorn app.main:app --reload           # http://localhost:8000
python -m pytest tests -q
```

Scheduled crawl (nightly, 1 hour):

```
0 2 * * * cd /path/to/datasets && python -m jobs.crawl >> data/crawl.log 2>&1
python -m jobs.crawl --query "pneumothorax chest x-ray" --minutes 15   # one-off
```

Docker: `docker build -t sauce-datasets . && docker run -p 8000:8000 -v $PWD/data:/data -e ANTHROPIC_API_KEY sauce-datasets`.
All settings are in `.env.example`.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/search?q=` | indexed results + matched conditions (with 510(k)) + latest crawl + `crawl_recommended` |
| POST | `/api/crawls` | `{mode: "query"\|"broad", query?, minutes?, force?}` → `{crawl_id, reused}` |
| GET | `/api/crawls`, `/api/crawls/{id}` | status, log, hits, new hits, tokens |
| POST | `/api/crawls/{id}/cancel` | stop at the next agent turn |
| GET | `/api/conditions?with_datasets=` | directory, 510(k)-ranked |
| POST | `/api/conditions/{name}/refresh-510k` | recount from openFDA |
| GET | `/api/datasets?condition=`, `/api/datasets/{id}` | cards (with files) |
| POST | `/api/datasets/{id}/download` | retry downloads |
| GET | `/files/{file_id}` | a collected file |

## Known limits (v0)

- **510(k) count is a proxy.** openFDA has no condition field; we count
  clearances whose `device_name` contains the condition or planner-proposed
  device terms. Brand-named AI devices ("… Triage", "icobrain") are missed, so
  counts run low (e.g. MS). Better source: FDA's AI-enabled device list joined to
  510(k) summaries, or an LLM pass over summary PDFs.
- **Catalog quality depends on the agents.** They are told to record only
  verified landing pages and never invent fields, but nothing re-verifies a card
  later. A periodic link-check / re-verify job is a natural next step.
- **Dedup is by canonical landing URL.** The same dataset mirrored on two hosts
  (e.g. Kaggle + Zenodo) becomes two cards.
- **In-process crawls.** Crawls run as threads in the API process; a restart
  marks running crawls `interrupted`. The CLI is the cron path. A job queue comes
  with the scheduler work.
- **Untrusted inputs.** URLs come from an LLM reading the open web: downloads are
  limited to flat-file types, size-capped, and blocked from private/loopback
  addresses (checked on every redirect hop). Files are never executed.
- **No auth.** Anyone who can reach the server can launch (paid) crawls. Put it
  behind the sauce.ai account layer before exposing it publicly.
- **Not yet run against the live API** in development (no key in the build
  environment); the agent loop is covered by scripted-client tests.

## Next

1. Scheduler (APScheduler or platform cron) for the nightly broad crawl.
2. Better 510(k) ranking (AI-enabled device list, product codes).
3. Re-verification + link-rot checks; merge duplicates across hosts.
4. Auth + per-user crawl budgets.
5. ETL/ingestion: schema inference for collected tables, DICOM/NIfTI metadata.
