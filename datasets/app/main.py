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
from .config import Settings, get_settings
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
               literature: LiteratureWorker | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or Store(settings.db_path)
    store.mark_stale_crawls()
    manager = manager or CrawlManager(store, settings)
    literature = literature or LiteratureWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    logging.basicConfig(level=logging.INFO)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.literature_enabled:
            literature.start()
        yield
        literature.stop()
        manager.shutdown()

    app = FastAPI(title="sauce.ai/datasets", lifespan=lifespan,
                  description="LLM-driven medical dataset finder", version="0.1.0")
    app.state.store, app.state.manager, app.state.settings = store, manager, settings
    app.state.literature = literature
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins or ["*"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return {"status": "ok", "llm_configured": manager.llm_ready(),
                "active_crawls": manager.active()}

    @app.get("/api/stats")
    def stats():
        lit = store.literature_summary()
        return {**store.stats(), "papers": lit["articles"], "active_crawls": manager.active(),
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
                                   "fda_510k_count": c["fda_510k_count"]})
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
        n = fda.refresh_condition(store, name)
        if n is None and not store.get_condition(name):
            raise HTTPException(404, "condition not found")
        return {"name": name, "fda_510k_count": n}

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
        return store.dataset_articles(ds_id, relation, limit, offset)

    @app.post("/api/datasets/{ds_id}/articles/refresh", status_code=202)
    def refresh_articles(ds_id: str):
        if not store.get_dataset(ds_id):
            raise HTTPException(404, "dataset not found")
        store.reset_literature(ds_id)
        return {"queued": True}

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
