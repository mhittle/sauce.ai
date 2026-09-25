"""FastAPI app for sauce.ai/datasets: search the catalog, launch crawls, serve
downloaded files, and the single-page UI.

    uvicorn app.main:app --reload      # dev
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import crawler, fda
import os

from .config import Settings, get_settings, on_mounted_volume, on_railway
from .devices import DeviceWorker, fda_database_url, fetch_one, summary_pdf_urls
from .literature import LiteratureWorker
from .manager import CrawlBusy, CrawlManager
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"


class CrawlRequest(BaseModel):
    mode: str = Field("query", pattern="^(query|broad)$")
    query: str | None = Field(None, max_length=500)
    minutes: int | None = Field(None, ge=1, le=180)
    force: bool = False


def create_app(settings: Settings | None = None, store: Store | None = None,
               manager: CrawlManager | None = None,
               literature: LiteratureWorker | None = None,
               devices: DeviceWorker | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or Store(settings.db_path)
    store.mark_stale_crawls()
    manager = manager or CrawlManager(store, settings)
    literature = literature or LiteratureWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    devices = devices or DeviceWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    logging.basicConfig(level=logging.INFO)

    def storage() -> dict:
        mounted = on_mounted_volume(settings.data_dir)
        configured = os.environ.get("DATASETS_DATA_DIR")
        db = settings.db_path
        return {
            "data_dir": str(settings.data_dir),
            "configured_data_dir": configured,
            "railway_volume": os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"),
            "redirected_to_volume": bool(configured) and
                Path(configured).resolve() != settings.data_dir.resolve(),
            "on_mounted_volume": mounted,
            # None = can't tell (local dev); False = will be lost on redeploy.
            "persistent": True if mounted else (False if on_railway() else None),
            "catalog_created_at": store.kv_get("catalog_created_at"),
            "opens": int(store.kv_get("opens") or 0),
            "db_bytes": db.stat().st_size if db.exists() else 0,
        }

    boot = storage()
    if boot["persistent"] is False:
        logging.getLogger(__name__).error(
            "STORAGE IS NOT PERSISTENT: %s is on the container's disk and will be wiped on"
            " redeploy. Attach a Railway volume to this service.", settings.data_dir)
    elif boot["redirected_to_volume"]:
        logging.getLogger(__name__).warning(
            "DATASETS_DATA_DIR=%s is outside the attached volume; using %s instead.",
            boot["configured_data_dir"], settings.data_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.literature_enabled:
            literature.start()
        if settings.devices_enabled:
            devices.start()
        yield
        literature.stop()
        devices.stop()
        manager.shutdown()

    app = FastAPI(title="sauce.ai/datasets", lifespan=lifespan,
                  description="LLM-driven medical dataset finder", version="0.1.0")
    app.state.store, app.state.manager, app.state.settings = store, manager, settings
    app.state.literature, app.state.devices = literature, devices
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins or ["*"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return {"status": "ok", "llm_configured": manager.llm_ready(),
                "active_crawls": manager.active(), "storage": storage()}

    @app.get("/api/stats")
    def stats():
        lit = store.literature_summary()
        return {**store.stats(), "papers": lit["articles"],
                "fda_submissions": store.device_summary()["devices"],
                "storage": storage(),
                "active_crawls": manager.active(),
                "llm_configured": manager.llm_ready()}

    # -------------------------------------------------------- search
    @app.get("/api/search")
    def search(q: str = Query(..., min_length=1, max_length=500),
               limit: int = Query(100, ge=1, le=500)):
        """Everything already indexed for q: memoized hits from earlier crawls
        of the same query first, then full-text matches widened by the
        synonyms of any condition q names."""
        memo = store.memo_for_query(q)
        cond_keys = store.match_conditions(q)
        extra = list(memo["expansion_terms"])
        conditions = []
        for k in cond_keys:
            c = store.get_condition(k)
            if c:
                extra += [c["name"], *c["synonyms"]]
                conditions.append({"name": c["name"], "display": c["display"],
                                   "fda_510k_count": c["fda_510k_count"],
                                   "fda_denovo_count": c.get("fda_denovo_count")})
        ids = list(dict.fromkeys(memo["dataset_ids"] + store.search(q, limit, extra)))
        recent = store.recent_crawl_for(q, settings.recrawl_hours)
        return {
            "query": q,
            "conditions": conditions,
            "results": store.get_datasets(ids[:limit]),
            "latest_crawl": memo["latest_crawl"],
            "recent_crawl": recent,
            "crawl_recommended": recent is None,
        }

    # -------------------------------------------------------- crawls
    @app.post("/api/crawls", status_code=202)
    def start_crawl(req: CrawlRequest):
        if req.mode == "query":
            if not (req.query or "").strip():
                raise HTTPException(422, "query is required for a query crawl")
            recent = store.recent_crawl_for(req.query, settings.recrawl_hours)
            if recent and not req.force:
                return {"crawl_id": recent["id"], "reused": True,
                        "status": recent["status"]}
        if not manager.llm_ready():
            raise HTTPException(503, "ANTHROPIC_API_KEY is not configured")
        try:
            cid = manager.start(req.mode, req.query, req.minutes)
        except CrawlBusy as exc:
            raise HTTPException(429, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {"crawl_id": cid, "reused": False, "status": "queued"}

    @app.get("/api/crawls")
    def list_crawls(limit: int = Query(20, ge=1, le=100)):
        return store.list_crawls(limit)

    @app.get("/api/crawls/{crawl_id}")
    def get_crawl(crawl_id: int):
        c = store.get_crawl(crawl_id)
        if not c:
            raise HTTPException(404, "crawl not found")
        c["active"] = crawl_id in manager.active()
        return c

    @app.post("/api/crawls/{crawl_id}/cancel")
    def cancel_crawl(crawl_id: int):
        if not manager.cancel(crawl_id):
            raise HTTPException(409, "crawl is not running")
        return {"cancelled": True}

    # -------------------------------------------------------- catalog
    @app.get("/api/conditions")
    def conditions(with_datasets: bool = False):
        return store.conditions_ranked(only_with_datasets=with_datasets)

    @app.post("/api/conditions/{name}/refresh-510k")
    def refresh_510k(name: str):
        if not store.get_condition(name):
            raise HTTPException(404, "condition not found")
        n = fda.refresh_condition(store, name)
        c = store.get_condition(name)
        return {"name": name, "fda_510k_count": n, "fda_denovo_count": c["fda_denovo_count"]}

    @app.get("/api/datasets")
    def datasets(condition: str | None = None, limit: int = Query(100, ge=1, le=500),
                 offset: int = Query(0, ge=0)):
        return store.get_datasets(store.list_dataset_ids(condition, limit, offset))

    @app.get("/api/datasets/{ds_id}")
    def dataset(ds_id: str):
        d = store.get_dataset(ds_id)
        if not d:
            raise HTTPException(404, "dataset not found")
        return d

    @app.get("/api/datasets/{ds_id}/articles")
    def dataset_articles(ds_id: str, relation: str | None = Query(None, pattern="^(cites|mentions)$"),
                         limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        """Papers linked to a dataset: descriptor paper(s), then papers citing
        them, then papers naming the dataset; most-cited first."""
        if not store.get_dataset(ds_id):
            raise HTTPException(404, "dataset not found")
        res = store.dataset_articles(ds_id, relation, limit, offset)
        used = store.devices_for_articles([a["id"] for a in res["items"]])
        for a in res["items"]:
            a["devices"] = used.get(a["id"], [])
        return res

    @app.post("/api/datasets/{ds_id}/articles/refresh", status_code=202)
    def refresh_articles(ds_id: str):
        if not store.get_dataset(ds_id):
            raise HTTPException(404, "dataset not found")
        store.reset_literature(ds_id)
        return {"queued": True}

    # -------------------------------------------------------- FDA devices
    @app.get("/api/devices")
    def list_devices(condition: str | None = None,
                     type: str | None = Query(None, pattern="^(510k|denovo|pma)$"),
                     category: str | None = Query(None, pattern="^(software|ai)$"),
                     q: str | None = Query(None, max_length=200),
                     dataset: str | None = None, linked: bool = False,
                     sort: str = "decision_date",
                     dir: str = Query("desc", pattern="^(asc|desc)$"),
                     limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        """510(k)/De Novo submissions, filterable by condition, type, text,
        software/AI category, or catalog dataset referenced; sortable by
        date, company, name…"""
        res = store.list_devices(condition, type, q, dataset, linked, category=category,
                                 sort=sort, direction=dir, limit=limit, offset=offset)
        if condition:
            res["condition"] = store.get_condition(condition)
        return res

    @app.get("/api/devices/{k}")
    def device(k: str):
        """Everything public about one submission: the openFDA record, links
        to FDA's database page and summary PDF, predicates, the catalog
        datasets/papers its summary references, and (once analysed) a
        structured summary of the PDF. Opening it queues the analysis."""
        k = k.upper()
        d = store.get_device(k)
        if not d and fetch_one(store, k, settings):
            d = store.get_device(k)  # e.g. a predicate outside our conditions
        if not d:
            raise HTTPException(404, "submission not found")
        doc = d["doc"] or {}
        wants_llm = settings.device_llm != "off" and devices.client_factory is not None
        if (not doc or doc.get("status") == "queued"
                or (wants_llm and doc.get("status") == "done" and not doc.get("extracted_at"))):
            if not doc.get("requested"):
                store.request_device_analysis(k)
                devices.poke()
            d["pending"] = True
        else:
            d["pending"] = bool(doc.get("requested"))
        d["fda_url"] = fda_database_url(k)
        d["pdf_url"] = doc.get("pdf_url") or summary_pdf_urls(k)[0]
        d["llm_available"] = wants_llm
        return d

    @app.post("/api/devices/{k}/analyze", status_code=202)
    def analyze_device(k: str):
        k = k.upper()
        if not store.get_device(k):
            raise HTTPException(404, "submission not found")
        store.request_device_analysis(k)
        devices.poke()
        return {"queued": True}

    @app.get("/api/devices-status")
    def devices_status():
        return {**store.device_summary(), "worker_running": devices.running(),
                "enabled": settings.devices_enabled, "llm_mode": settings.device_llm,
                "last_error": devices.last_error}

    @app.get("/api/literature")
    def literature_status():
        return {**store.literature_summary(), "worker_running": literature.running(),
                "enabled": settings.literature_enabled,
                "openalex": bool(settings.openalex_api_key),
                "last_error": literature.last_error}

    @app.post("/api/datasets/{ds_id}/download", status_code=202)
    def retry_download(ds_id: str):
        if not store.get_dataset(ds_id):
            raise HTTPException(404, "dataset not found")
        manager.queue_download(ds_id)
        return {"queued": True}

    @app.get("/files/{file_id}")
    def get_file(file_id: int):
        f = store.get_file(file_id)
        if not f or f["status"] != "downloaded" or not f["local_path"]:
            raise HTTPException(404, "file not available")
        path = Path(f["local_path"]).resolve()
        if settings.files_dir.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "file not available")
        return FileResponse(path, filename=f["filename"] or path.name)

    # -------------------------------------------------------- UI
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
