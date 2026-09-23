"""FastAPI app: researcher UI, run submission, status, report, export."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import adjudication as adj
from . import compare as cmp_mod
from . import dataset
from .catalog import HARM_CATEGORIES, SEVERITY_LEVELS, SPECIALTIES, TACTICS, QalyAssumptions, specialty_options
from .config import Settings, get_settings
from .netguard import UnsafeTarget, check_url
from .providers import PROVIDERS, available_providers, model_catalog
from .runner import Runner, RunQueue, RunSpec
from .store import QuotaExceeded, Store
from .targets import TARGET_KINDS, TargetConfig, validate_config

STATIC = Path(__file__).parent / "static"


class TargetIn(BaseModel):
    kind: str
    url: str = ""
    model: str = ""
    api_key: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    system_prompt: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str = ""
    response_path: str = ""
    stateful: bool = False
    input_selector: str = ""
    send_selector: str = ""
    response_selector: str = ""


class RunIn(BaseModel):
    email: str
    n_trials: int
    specialty: str
    condition: str = ""
    focus_harms: list[str] = Field(default_factory=list)
    max_turns: int = 8
    stop_on_harm: bool = True
    control_fraction: float = 0.0
    harm_threshold: float = 0.10
    notes: str = ""
    seed: int = 0
    qaly: dict = Field(default_factory=dict)
    orchestration: dict = Field(default_factory=dict)
    judges: list[str] = Field(default_factory=list)
    target: TargetIn


class AdjudicationSetIn(BaseModel):
    run_ids: list[str]
    name: str = ""
    n: int = 120
    seed: int = 0
    by_specialty: bool = True
    by_tactic: bool = False
    allocation: str = "proportional"


class LabelIn(BaseModel):
    rater: str
    harmful: bool
    severity: int | None = None
    categories: list[str] = Field(default_factory=list)
    escalated: bool | None = None
    confidence: int | None = None
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


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    head = (name[:2] + "***") if len(name) > 2 else "***"
    return f"{head}@{domain}"


def create_app(settings: Settings | None = None, store: Store | None = None,
               runner: Runner | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or Store(settings.db_path)
    runner = runner or Runner(settings, store)
    queue = RunQueue(runner)
    queue.recover()
    submit_limiter = SlidingWindow(limit=5, window_s=3600)

    app = FastAPI(title="sauce.ai/redteam", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.store = store
    app.state.queue = queue

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/config")
    def config():
        return {
            "specialties": specialty_options(),
            "harm_categories": HARM_CATEGORIES,
            "tactics": TACTICS,
            "severity_levels": SEVERITY_LEVELS,
            "target_kinds": list(TARGET_KINDS),
            "providers": list(PROVIDERS),
            "available_providers": available_providers(settings),
            "model_catalog": model_catalog(settings),
            "defaults": {
                "attackers": list(settings.default_attackers),
                "arbiters": [settings.default_arbiter],
                "judges": list(settings.default_judges),
                "qaly": QalyAssumptions().__dict__,
            },
            "limits": {
                "free_trial_limit": settings.free_trial_limit,
                "max_turns_cap": settings.max_turns_cap,
                "price_per_trial_usd": settings.price_per_trial_usd,
            },
        }

    @app.get("/quota/{email}")
    def quota(email: str):
        used = store.trials_used(email)
        return {"used": used, "limit": settings.free_trial_limit,
                "remaining": max(0, settings.free_trial_limit - used)}

    @app.post("/runs")
    def submit(body: RunIn, request: Request):
        ip = request.client.host if request.client else "?"
        if not submit_limiter.allow(ip):
            raise HTTPException(429, "too many submissions from this address; try again later")

        target = TargetConfig(**body.target.model_dump())
        spec = RunSpec(**{k: v for k, v in body.model_dump().items() if k != "target"})
        try:  # structural validation (no network) before spending quota
            spec.validate(settings)
            validate_config(target)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        price = round(spec.n_trials * settings.price_per_trial_usd, 2)
        try:
            store.reserve_trials(spec.email, spec.n_trials, settings.free_trial_limit)
        except QuotaExceeded as exc:
            raise HTTPException(402, str(exc))

        try:  # DNS-based SSRF gate is the last check; refund the reservation if it fails
            if target.url:
                check_url(target.url, settings.allow_private_targets)
        except (ValueError, UnsafeTarget) as exc:
            store.refund_trials(spec.email, spec.n_trials)
            raise HTTPException(400, str(exc))

        run_id = store.create_run(spec.email, spec.n_trials, spec.public_dict(settings),
                                  target.public_dict(), price)
        queue.submit(run_id, spec, target)
        return {"run_id": run_id, "status": "queued",
                "poll": f"/runs/{run_id}/status", "report": f"/runs/{run_id}"}

    @app.get("/runs/{run_id}/status")
    def status(run_id: str):
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "unknown run")
        adv = (run.get("summary") or {}).get("adversarial") if run.get("summary") else None
        return {
            "run_id": run_id,
            "status": run["status"],
            "n_trials": run["n_trials"],
            "completed_trials": run["completed_trials"],
            "email": _mask(run["email"]),
            "error": run["error"],
            "emailed": bool(run["emailed_at"]),
            "headline": None if not adv else {
                "conversation_risk": adv["conversation_risk"]["value"],
                "trials_with_harm": adv["trials_with_harm"],
                "harmful_responses": adv["harmful_responses"],
            },
        }

    @app.post("/runs/{run_id}/cancel")
    def cancel(run_id: str):
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "unknown run")
        queue.cancel(run_id)
        return {"run_id": run_id, "cancelling": True}

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def report(run_id: str):
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "unknown run")
        if run["status"] == "complete" and run.get("report_html"):
            return HTMLResponse(run["report_html"])
        pct = int(100 * run["completed_trials"] / max(1, run["n_trials"]))
        msg = {"queued": "Queued.", "running": f"Running: {run['completed_trials']}/{run['n_trials']} trials ({pct}%).",
               "failed": f"Failed: {run['error']}"}.get(run["status"], run["status"])
        refresh = "" if run["status"] in ("failed",) else '<meta http-equiv="refresh" content="5">'
        return HTMLResponse(
            f'<!doctype html><meta charset=utf-8>{refresh}<title>Run {run_id}</title>'
            f'<body style="font:16px system-ui;max-width:640px;margin:60px auto;padding:0 16px">'
            f'<h1>Red-team run {run_id}</h1><p>{msg}</p>'
            f'<div style="height:10px;background:#eee;border-radius:5px;overflow:hidden">'
            f'<div style="height:100%;width:{pct}%;background:#2a78d6"></div></div>'
            f'<p style="color:#666">This page refreshes automatically. The full report is emailed when the run completes.</p></body>')

    @app.get("/runs/{run_id}/export")
    def export(run_id: str):
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "unknown run")
        return JSONResponse({
            "run": {k: run[k] for k in ("id", "status", "n_trials", "completed_trials",
                                        "created_at", "finished_at", "price_usd")},
            "config": run["config"], "target": run["target"],
            "summary": run["summary"], "bandit": run["bandit"], "usage": run["usage"],
            "trials": store.trials_for_run(run_id),
        })

    # -- adjudication (clinician judge-validation study) -------------------

    @app.post("/adjudication/sets")
    def create_adjudication_set(body: AdjudicationSetIn):
        run_ids = [r.strip() for r in body.run_ids if r.strip()]
        if not run_ids:
            raise HTTPException(400, "at least one run_id is required")
        turns = []
        for rid in run_ids:
            run = store.get_run(rid)
            if not run:
                raise HTTPException(404, f"unknown run {rid}")
            turns.extend(adj.turns_from_trials(rid, store.trials_for_run(rid)))
        if not turns:
            raise HTTPException(400, "the selected runs have no completed replies to adjudicate")
        spec = adj.SampleSpec(n=body.n, seed=body.seed, by_specialty=body.by_specialty,
                              by_tactic=body.by_tactic, allocation=body.allocation)
        sampled = adj.stratified_sample(turns, spec)
        # attach the judge's stored verdict per sampled turn (kept out of the blinded view)
        judged = {}
        for rid in run_ids:
            for t in store.trials_for_run(rid):
                for u in t["turns"]:
                    judged[u["id"]] = (u["p_harm"], bool(u["harmful"]))
        items = [{
            "turn_id": s.turn_id, "run_id": s.run_id, "stratum": s.stratum, "harm_bin": s.harm_bin,
            "inclusion_prob": s.inclusion_prob,
            "judge_p_harm": judged.get(s.turn_id, (None, None))[0],
            "judge_harmful": judged.get(s.turn_id, (None, None))[1],
            "context": s.context,
        } for s in sampled]
        name = body.name.strip() or f"adjudication of {len(run_ids)} run(s)"
        set_id = store.create_adjudication_set(name, spec.__dict__, run_ids, items)
        base = settings.public_base_url.rstrip("/")
        return {"set_id": set_id, "n_items": len(items),
                "label_url": f"{base}/adjudicate/{set_id}",
                "analysis_url": f"{base}/adjudication/{set_id}/analysis"}

    @app.get("/adjudication/{set_id}/items")
    def adjudication_items(set_id: str):
        s = store.get_adjudication_set(set_id)
        if not s:
            raise HTTPException(404, "unknown adjudication set")
        return {"set_id": set_id, "name": s["name"], "n_items": s["n_items"],
                "harm_categories": HARM_CATEGORIES, "severity_levels": SEVERITY_LEVELS,
                "items": store.adjudication_items(set_id, blinded=True)}

    @app.post("/adjudication/{set_id}/items/{item_id}/label")
    def submit_label(set_id: str, item_id: int, body: LabelIn):
        s = store.get_adjudication_set(set_id)
        if not s:
            raise HTTPException(404, "unknown adjudication set")
        rater = body.rater.strip()
        if not rater:
            raise HTTPException(400, "a rater id is required")
        if body.severity is not None and not 0 <= body.severity <= 4:
            raise HTTPException(400, "severity must be 0–4")
        cats = [c for c in body.categories if c in HARM_CATEGORIES]
        store.submit_label(set_id, item_id, rater, harmful=body.harmful, severity=body.severity,
                           categories=cats, escalated=body.escalated, confidence=body.confidence,
                           notes=body.notes.strip()[:2000] or None)
        return {"ok": True, "progress": store.adjudication_progress(set_id)}

    @app.get("/adjudication/{set_id}/analysis")
    def adjudication_analysis(set_id: str):
        s = store.get_adjudication_set(set_id)
        if not s:
            raise HTTPException(404, "unknown adjudication set")
        items = store.adjudication_items(set_id, blinded=False)
        labels = store.adjudication_labels(set_id)
        return {"set_id": set_id, "name": s["name"], "spec": s["spec"],
                "progress": store.adjudication_progress(set_id),
                **adj.analyze_set(items, labels)}

    @app.get("/adjudication/{set_id}/export")
    def adjudication_export(set_id: str):
        s = store.get_adjudication_set(set_id)
        if not s:
            raise HTTPException(404, "unknown adjudication set")
        return JSONResponse({"set": s, "items": store.adjudication_items(set_id, blinded=False),
                             "labels": store.adjudication_labels(set_id)})

    # -- tidy dataset export + cross-model comparison (research Phase B) ----

    def _run_ids(runs: str) -> list[str]:
        ids = [r.strip() for r in runs.split(",") if r.strip()]
        if not ids:
            raise HTTPException(400, "pass ?runs=<run_id>[,<run_id>...]")
        missing = [r for r in ids if not store.get_run(r)]
        if missing:
            raise HTTPException(404, f"unknown run(s): {', '.join(missing)}")
        return ids

    @app.get("/export/tidy.csv", response_class=PlainTextResponse)
    def export_tidy(runs: str = Query(...), level: str = "turn"):
        if level not in ("turn", "trial"):
            raise HTTPException(400, "level must be 'turn' or 'trial'")
        rows, cols = dataset.build(store, _run_ids(runs), level=level)
        fname = f"redteam-tidy-{level}.csv"
        return PlainTextResponse(dataset.to_csv(rows, cols), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.get("/export/tidy.json")
    def export_tidy_json(runs: str = Query(...), level: str = "turn"):
        if level not in ("turn", "trial"):
            raise HTTPException(400, "level must be 'turn' or 'trial'")
        rows, cols = dataset.build(store, _run_ids(runs), level=level)
        return {"level": level, "columns": cols, "n_rows": len(rows), "rows": rows}

    @app.get("/compare", response_class=HTMLResponse)
    def compare_html(runs: str = Query(...)):
        return HTMLResponse(cmp_mod.render_comparison_html(cmp_mod.compare_runs(store, _run_ids(runs))))

    @app.get("/compare.json")
    def compare_json(runs: str = Query(...)):
        return cmp_mod.compare_runs(store, _run_ids(runs))

    @app.get("/adjudicate/{set_id}", response_class=HTMLResponse)
    def adjudicate_ui(set_id: str):
        if not store.get_adjudication_set(set_id):
            raise HTTPException(404, "unknown adjudication set")
        f = STATIC / "adjudicate.html"
        return HTMLResponse(f.read_text() if f.exists() else "<h1>adjudication</h1>")

    @app.get("/", response_class=HTMLResponse)
    def index():
        f = STATIC / "index.html"
        return HTMLResponse(f.read_text() if f.exists() else "<h1>sauce.ai/redteam</h1>")

    return app


app = create_app() if os.environ.get("REDTEAM_EAGER_APP") else None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
