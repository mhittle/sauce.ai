"""FastAPI app: request form, job submission, status, report, export."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import catalog as C
from .config import Settings, get_settings
from .pipeline import JobQueue, JobSpec, Runner
from .store import Store

STATIC = Path(__file__).parent / "static"
STAGES = ["search", "screen", "snowball", "extract", "grade", "done"]


class JobIn(BaseModel):
    condition: str
    synonyms: list[str] = Field(default_factory=list)
    intended_use: str = "prevalence"
    data_types: list[str] = Field(default_factory=lambda: ["claims"])
    coding_era: str = "icd10"
    country: str = ""
    expected_prevalence: float | None = None
    max_records: int = 150
    max_extract: int = 25
    snowball: bool = True
    model_suggestions: bool = True
    email: str = ""
    notes: str = ""


class SlidingWindow:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def create_app(settings: Settings | None = None, store: Store | None = None,
               runner: Runner | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or Store(settings.db_path)
    runner = runner or Runner(settings, store)
    queue = JobQueue(runner)
    queue.recover()
    limiter = SlidingWindow(settings.jobs_per_hour_per_ip, 3600)

    app = FastAPI(title="sauce.ai/phenotype", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.queue = queue

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/config")
    def config():
        return {
            "intended_uses": {k: {"label": v["label"], "help": v["help"]} for k, v in C.INTENDED_USES.items()},
            "data_types": C.DATA_TYPES,
            "coding_eras": C.CODING_ERAS,
            "limits": {"max_records_cap": settings.max_records_cap, "max_extract_cap": settings.max_extract_cap},
            "models": {"screen": settings.screen_model, "extract": settings.extract_model},
            "exemplar": {"condition": C.EXEMPLAR["condition"], "citation": C.EXEMPLAR["citation"]},
        }

    @app.post("/jobs")
    def submit(body: JobIn, request: Request):
        ip = request.client.host if request.client else "?"
        spec = JobSpec(**body.model_dump())
        try:
            spec.validate(settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not limiter.allow(ip):
            raise HTTPException(429, "too many reviews from this address; try again later")
        job_id = store.create_job(spec.email, asdict(spec))
        queue.submit(job_id, spec)
        # Relative links so the service works behind a path prefix (sauce.ai/phenotype/).
        return {"job_id": job_id, "status": "queued", "poll": f"jobs/{job_id}/status", "report": f"jobs/{job_id}"}

    def _job(job_id: str) -> dict:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        return job

    @app.get("/jobs/{job_id}/status")
    def status(job_id: str):
        job = _job(job_id)
        res = job.get("result") or {}
        top = (res.get("candidates") or [None])[0]
        return {"job_id": job_id, "status": job["status"], "stage": job["stage"],
                "progress": job.get("progress"), "error": job["error"], "emailed": bool(job["emailed_at"]),
                "top": None if not top else {"name": top["algorithm"]["name"], "grade": top["grade"]["label"]},
                "n_candidates": len(res.get("candidates") or [])}

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        _job(job_id)
        queue.cancel(job_id)
        return {"job_id": job_id, "cancelling": True}

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def report(job_id: str):
        job = _job(job_id)
        if job["status"] == "complete" and job.get("report_html"):
            return HTMLResponse(job["report_html"])
        prog = job.get("progress") or {}
        stage = job["stage"] or "queued"
        step = STAGES.index(stage) + 1 if stage in STAGES else 0
        pct = int(100 * step / len(STAGES))
        if stage == "extract" and prog.get("extract_total"):
            pct = int(100 * (3 + prog["extract_done"] / prog["extract_total"]) / len(STAGES))
        msg = {"queued": "Queued.", "failed": f"Failed: {job['error']}", "cancelled": "Cancelled."}.get(
            job["status"], f"Working: {stage}.")
        refresh = "" if job["status"] in ("failed", "cancelled") else '<meta http-equiv="refresh" content="5">'
        return HTMLResponse(
            f'<!doctype html><meta charset=utf-8>{refresh}<title>Review {job_id}</title>'
            f'<body style="font:16px system-ui;max-width:640px;margin:60px auto;padding:0 16px">'
            f'<h1>Phenotype review {job_id}</h1><p>{escape(msg)}</p>'
            f'<div style="height:10px;background:#eee;border-radius:5px;overflow:hidden">'
            f'<div style="height:100%;width:{pct}%;background:#2a78d6"></div></div>'
            f'<p style="color:#666">This page refreshes automatically. A review usually takes 3&ndash;10 minutes.</p></body>')

    @app.get("/jobs/{job_id}/export")
    def export(job_id: str):
        job = _job(job_id)
        return JSONResponse({"job": {k: job[k] for k in ("id", "status", "created_at", "finished_at")},
                             "result": job.get("result")})

    @app.get("/jobs/{job_id}/algorithms/{rank}.sql", response_class=PlainTextResponse)
    def sql(job_id: str, rank: int):
        cands = (_job(job_id).get("result") or {}).get("candidates") or []
        if not 1 <= rank <= len(cands):
            raise HTTPException(404, "no such algorithm")
        return PlainTextResponse(cands[rank - 1]["omop_sql"])

    @app.get("/", response_class=HTMLResponse)
    def index():
        f = STATIC / "index.html"
        return HTMLResponse(f.read_text() if f.exists() else "<h1>sauce.ai/phenotype</h1>")

    return app


app = create_app() if os.environ.get("PHENOTYPE_EAGER_APP") else None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
