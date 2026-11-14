"""FastAPI app for Palo Alto Health Labs Datasets: search the catalog, launch crawls, serve
downloaded files, and the single-page UI.

    uvicorn app.main:app --reload      # dev
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import crawler, fda
import os

from .config import Settings, get_settings, on_mounted_volume, on_railway
from .devices import DeviceWorker, fda_database_url, fetch_one, summary_pdf_urls
from .compat import CompatWorker
from .coscientist import CoScientist
from .explore import ExploreChat, ExploreManager
from .explore_sources import SourceError, file_url
from .importers import SOURCES, ImportRunner
from .literature import LiteratureWorker
from .manager import CrawlBusy, CrawlManager
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(..., min_length=1, max_length=40)


class EditRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)


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
    pruned = store.run_once("prune_literature_noise_v1", store.prune_literature_noise)
    if pruned:
        logging.getLogger(__name__).info("pruned literature noise: %s", pruned)
    manager = manager or CrawlManager(store, settings)
    literature = literature or LiteratureWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    devices = devices or DeviceWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    compat = CompatWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    explorer = ExploreManager(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    importer = ImportRunner(
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
        if settings.compat_enabled:
            compat.start()
        yield
        compat.stop()
        literature.stop()
        devices.stop()
        manager.shutdown()

    app = FastAPI(title="Palo Alto Health Labs Datasets", lifespan=lifespan,
                  description="LLM-driven medical dataset finder", version="0.1.0")
    app.state.store, app.state.manager, app.state.settings = store, manager, settings
    app.state.literature, app.state.devices = literature, devices
    app.state.importer = importer
    app.state.compat = compat
    app.state.explorer = explorer
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

    # -------------------------------------------------------- bulk imports
    @app.get("/api/imports")
    def import_status():
        return {"busy": importer.busy(), "llm": bool(settings.anthropic_api_key),
                "sources": importer.status()}

    @app.post("/api/imports/{source}", status_code=202)
    def start_import(source: str):
        if source not in SOURCES:
            raise HTTPException(404, "unknown source")
        if not importer.start(source):
            raise HTTPException(409, "an import is already running")
        return {"started": source}

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

    @app.get("/api/crawls/{crawl_id}/datasets")
    def crawl_datasets(crawl_id: int):
        """Dataset cards a crawl recorded (new ones first, then updated), each
        flagged is_new — what the crawl found, in the order it found them."""
        c = store.get_crawl(crawl_id)
        if not c:
            raise HTTPException(404, "crawl not found")
        new = set(c["new_hits"])
        ordered = [i for i in c["hits"] if i in new] + [i for i in c["hits"] if i not in new]
        items = store.get_datasets(ordered)
        for d in items:
            d["is_new"] = d["id"] in new
        return {"crawl_id": crawl_id, "status": c["status"], "items": items}

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

    @app.get("/api/datasets/browse")
    def browse(q: str | None = Query(None, max_length=200), condition: str | None = None,
               modality: str | None = None, access: str | None = None,
               source: str | None = None, repositories: bool = False,
               sort: str = Query("papers", pattern="^(papers|title|newest|compatible)$"),
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        """Browse every dataset: filter by text, condition, data type, access, source."""
        return store.browse_datasets(q, condition, modality, access, source, repositories,
                                     sort, limit, offset)

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

    @app.get("/api/articles")
    def articles(q: str | None = None, dataset: str | None = None, condition: str | None = None,
                 relation: str | None = Query(None, pattern="^(descriptor|cites|mentions)$"),
                 fda: bool = False,
                 sort: str = Query("cited_by_count", pattern="^(cited_by_count|year|title|venue|datasets)$"),
                 dir: str = Query("desc", pattern="^(asc|desc)$"),
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        """All papers linked to catalog datasets, most-cited first by default."""
        res = store.list_articles(q=q.strip() if q else None, dataset_id=dataset,
                                  condition=condition, relation=relation, fda_only=fda,
                                  sort=sort, direction=dir, limit=limit, offset=offset)
        used = store.devices_for_articles([a["id"] for a in res["items"]])
        for a in res["items"]:
            a["devices"] = used.get(a["id"], [])
        if dataset:
            d = store.get_dataset(dataset)
            res["dataset"] = {"id": dataset, "title": d["title"]} if d else None
        return res

    @app.get("/api/datasets/{ds_id}/compatible")
    def dataset_compatible(ds_id: str, limit: int = Query(50, ge=1, le=200)):
        """Other datasets usable in the same model or study: pooled training,
        external validation or pretraining, with harmonization steps."""
        d = store.get_dataset(ds_id)
        if not d:
            raise HTTPException(404, "dataset not found")
        return {"profile": d["profile"], "items": store.compatible(ds_id, limit)}

    # -------------------------------------------------------- explore
    def _check_token(token: str | None) -> None:
        if settings.edit_token and token != settings.edit_token:
            raise HTTPException(401, "edit token required")

    def _src(ds_id: str):
        try:
            return explorer.source(ds_id)
        except SourceError as exc:
            raise HTTPException(409, str(exc))

    def _call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except SourceError as exc:
            raise HTTPException(502, str(exc))
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, f"bad request: {exc}")

    @app.get("/api/explore/{ds_id}")
    def explore_get(ds_id: str):
        ds = store.get_dataset(ds_id)
        if not ds:
            raise HTTPException(404, "dataset not found")
        ex = explorer.get(ds_id) or {"status": "none", "spec": None}
        if ex.get("source"):
            ex["source"] = {k: v for k, v in ex["source"].items() if k != "paths"}
            probe = ex["source"].get("probe") or {}
            probe.pop("record_labels", None)
        return {**ex, "busy": explorer.busy(ds_id), "availability": explorer.availability(ds),
                "edit_locked": bool(settings.edit_token), "llm": bool(settings.anthropic_api_key),
                "chat_locked": bool(settings.edit_token) and not settings.chat_open,
                "dataset": {k: ds.get(k) for k in ("id", "title", "source", "url", "access_type",
                                                   "access_instructions", "description")}}

    @app.post("/api/explore/{ds_id}/build", status_code=202)
    def explore_build(ds_id: str, x_edit_token: str | None = Header(None)):
        _check_token(x_edit_token)
        if not store.get_dataset(ds_id):
            raise HTTPException(404, "dataset not found")
        if not explorer.build(ds_id):
            raise HTTPException(409, "already building")
        return {"building": True}

    @app.post("/api/explore/{ds_id}/edit")
    def explore_edit(ds_id: str, req: EditRequest, x_edit_token: str | None = Header(None)):
        _check_token(x_edit_token)
        return _call(explorer.edit, ds_id, req.prompt)

    chat = ExploreChat(explorer)

    @app.post("/api/explore/{ds_id}/chat")
    def explore_chat(ds_id: str, req: ChatRequest, x_edit_token: str | None = Header(None)):
        """Ask questions about the dataset; Claude answers by querying its sample."""
        if not settings.chat_open:
            _check_token(x_edit_token)
        return _call(chat.ask, ds_id, [t.model_dump() for t in req.messages])

    cosci = CoScientist(explorer)
    app.state.coscientist = cosci

    @app.get("/api/explore/{ds_id}/hypotheses")
    def hypotheses_get(ds_id: str):
        """The latest Co-Scientist run: progress log while running, then the
        10 candidates, the review and the 5 selected."""
        return cosci.latest(ds_id) or {"status": "none"}

    @app.post("/api/explore/{ds_id}/hypotheses", status_code=202)
    def hypotheses_start(ds_id: str, x_edit_token: str | None = Header(None)):
        _check_token(x_edit_token)
        if not store.get_dataset(ds_id):
            raise HTTPException(404, "dataset not found")
        try:
            return {"run": cosci.start(ds_id)}
        except SourceError as exc:
            raise HTTPException(409, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/explore/{ds_id}/revert/{version}")
    def explore_revert(ds_id: str, version: int, x_edit_token: str | None = Header(None)):
        _check_token(x_edit_token)
        _call(explorer.revert, ds_id, version)
        return {"ok": True}

    def _where(where: str | None) -> dict | None:
        if not where:
            return None
        k, _, v = where.partition(":")
        return {k: v}

    @app.get("/api/explore/{ds_id}/rows")
    def explore_rows(ds_id: str, where: str | None = None, offset: int = Query(0, ge=0),
                     length: int = Query(24, ge=1, le=100), columns: str | None = None):
        src = _src(ds_id)
        if src.__class__.__name__ == "HFSource":
            return _call(src.rows, _where(where), offset, length)
        if getattr(src, "kind", "") == "images":
            return _call(src.image_rows, _where(where), offset, length,
                         lambda i: file_url(ds_id, i))
        if not getattr(src, "has_table", lambda: False)():
            raise HTTPException(400, "no table")
        return _call(src.table_rows, _where(where), offset, length,
                     columns.split(",") if columns else None)

    @app.get("/api/explore/{ds_id}/file/{i}")
    def explore_file(ds_id: str, i: int):
        src = _src(ds_id)
        imgs = src.images() if hasattr(src, "images") else []
        if not 0 <= i < len(imgs):
            raise HTTPException(404, "no such file")
        name = (imgs[i][1] or imgs[i][0]).lower()
        ctype = ("image/png" if name.endswith(".png") else "image/jpeg"
                 if name.endswith((".jpg", ".jpeg")) else "application/octet-stream")
        return Response(src.read_bytes(imgs[i]), media_type=ctype,
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/explore/{ds_id}/distribution")
    def explore_distribution(ds_id: str, field: str, group_by: str | None = None,
                             bins: int = Query(20, ge=2, le=100)):
        src = _src(ds_id)
        probe0 = ((explorer.get(ds_id) or {}).get("source") or {}).get("probe") or {}
        if getattr(src, "kind", "") == "images" and field in (probe0.get("stats") or {}):
            return {"type": "categorical",
                    "groups": [{"group": "all", "counts": probe0["stats"][field]["frequencies"]}]}
        if getattr(src, "kind", "") == "images" and field == "label" and probe0.get("labels"):
            return {"type": "categorical", "groups": [{"group": "all", "counts": probe0["labels"]}]}
        if hasattr(src, "distribution") and src.has_table():
            try:
                return src.distribution(field, group_by, bins)
            except SourceError:
                if not (src.kind == "signals" and field == "label"):
                    raise HTTPException(404, f"no distribution for {field}")
        probe = ((explorer.get(ds_id) or {}).get("source") or {}).get("probe") or {}
        if field in (probe.get("stats") or {}):
            st = probe["stats"][field]
            if st.get("frequencies"):
                return {"type": "categorical", "groups": [{"group": "all", "counts": st["frequencies"]}]}
            if st.get("histogram"):
                h = st["histogram"]
                return {"type": "histogram", "edges": h["bin_edges"],
                        "groups": [{"group": "all", "counts": h["hist"]}]}
        if probe.get("labels") and field in ("label", ((probe.get("join") or {}).get("label_col"))):
            return {"type": "categorical", "groups": [{"group": "all", "counts": probe["labels"]}]}
        raise HTTPException(404, f"no distribution for {field}")

    @app.get("/api/explore/{ds_id}/summary")
    def explore_summary(ds_id: str, group_by: str, fields: str):
        src = _src(ds_id)
        if not hasattr(src, "group_summary") or not src.has_table():
            raise HTTPException(400, "not a table")
        return _call(src.group_summary, fields.split(","), group_by)

    def _series_cfg(ds_id: str) -> dict | None:
        spec = (explorer.get(ds_id) or {}).get("spec") or {}
        return spec.get("series")

    @app.get("/api/explore/{ds_id}/records")
    def explore_records(ds_id: str, label: str | None = None):
        src = _src(ds_id)
        if src.__class__.__name__ == "WFDBSource":
            per = (((explorer.get(ds_id) or {}).get("source") or {}).get("probe") or {}).get(
                "record_labels") or {}
            recs = [{"id": r, "labels": per.get(r, [])} for r in _call(src.records)]
        elif getattr(src, "kind", "") == "signals":
            recs = _call(src.file_records, _series_cfg(ds_id))
        else:
            cfg = _series_cfg(ds_id)
            if not cfg:
                raise HTTPException(400, "no series configured")
            recs = _call(src.series_records, cfg["id_col"], cfg.get("label_col"))
        if label:
            recs = [r for r in recs if label in r["labels"]]
        return {"records": recs[:1000], "total": len(recs)}

    @app.get("/api/explore/{ds_id}/signal")
    def explore_signal(ds_id: str, record: str, start: float = 0, dur: float = 10,
                       channels: str | None = None):
        src = _src(ds_id)
        chans = channels.split(",") if channels else None
        if src.__class__.__name__ == "WFDBSource":
            return _call(src.window, record, start, dur, chans)
        if getattr(src, "kind", "") == "signals":
            return _call(src.file_window, _series_cfg(ds_id), record, start, dur)
        cfg = _series_cfg(ds_id)
        if not cfg:
            raise HTTPException(400, "no series configured")
        return _call(src.series_window, cfg, record, start, dur, chans)

    @app.get("/api/explore/{ds_id}/traces")
    def explore_traces(ds_id: str, channel: str | None = None, label: str | None = None,
                       n: int = Query(12, ge=1, le=50), window: float = Query(10, gt=0, le=600),
                       align: str = "event"):
        src = _src(ds_id)
        if src.__class__.__name__ == "WFDBSource":
            return _call(src.traces, channel, label, n, window, align)
        if getattr(src, "kind", "") == "signals":
            return _call(src.file_traces, _series_cfg(ds_id), label, n, None)
        cfg = _series_cfg(ds_id)
        if not cfg:
            raise HTTPException(400, "no series configured")
        return _call(src.series_traces, cfg, channel or cfg["channels"][0], label, n, window)

    @app.get("/api/explore-requests")
    def explore_requests():
        """Views users asked for that the template library doesn't have yet."""
        with store._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT r.dataset_id, d.title, r.request, r.at FROM explore_requests r"
                " LEFT JOIN datasets d ON d.id = r.dataset_id ORDER BY r.id DESC LIMIT 200")]

    @app.get("/api/compat")
    def compat_status():
        raw = store.kv_get("compat_computed")
        return {"enabled": settings.compat_enabled, "worker_running": compat.running(),
                "last": json.loads(raw) if raw else None, "last_error": compat.last_error}

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
        raw = store.kv_get("fda_recent_sync")
        res["recent_sync"] = json.loads(raw) if raw else None
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
