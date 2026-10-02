"""FastAPI app: researcher UI, run submission, status, report, export."""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import adjudication as adj
from . import che
from . import che_report
from . import che_review
from . import che_screener
from . import compare as cmp_mod
from . import ablation as abl_mod
from . import card as card_mod
from . import daly as daly_mod
from . import epi as epi_mod
from . import target_trial as tt_mod
from . import strobe as strobe_mod
from . import table1 as table1_mod
from . import causal as causal_mod
from . import dataset
from . import field as field_mod
from . import guide as guide_mod
from . import grader_audit as gaudit
from . import leaderboard as lb_mod
from . import power as power_mod
from . import repro as repro_mod
from .catalog import HARM_CATEGORIES, SEVERITY_LEVELS, SPECIALTIES, TACTICS, QalyAssumptions, specialty_options
from .config import Settings, get_settings
from .netguard import UnsafeTarget, check_url
from .providers import PROVIDERS, available_providers, build_model, model_catalog, parse_spec
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


class AblationIn(RunIn):
    arms: list[str] = Field(default_factory=list)


class GraderAuditIn(BaseModel):
    judges: list[str] = Field(default_factory=list)
    threshold: float = 0.10


class FieldScanIn(BaseModel):
    email: str
    specialty: str
    condition: str = ""
    n_trials: int = 20
    seed: int = 0
    max_turns: int = 8
    harm_threshold: float = 0.10
    models: list[str] = Field(default_factory=list)  # panel keys; empty = all available
    orchestration: dict = Field(default_factory=dict)
    judges: list[str] = Field(default_factory=list)


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


class CheScreenIn(BaseModel):
    screener_model: str = ""
    seed: int = 0


class CheReviewSetIn(BaseModel):
    run_ids: list[str]
    name: str = ""
    neg_sample_rate: float | None = None
    seed: int = 0


class CheLabelIn(BaseModel):
    rater: str
    rater_type: str = "clinician_1"
    severity: int
    life_threatening: bool = False
    likelihood: str = "low"
    actionable: bool = False
    pathway: str = "other"
    rationale: str = ""


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
    audit_pool = ThreadPoolExecutor(max_workers=1)
    submit_limiter = SlidingWindow(limit=5, window_s=3600)

    app = FastAPI(title="sauce.ai/redteam", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.store = store
    app.state.queue = queue
    lb_mod.rebuild(store)  # stored scores follow the current definition

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
            f'<div style="height:100%;width:{pct}%;background:#8e2a1f"></div></div>'
            f'<p style="color:#666">This page refreshes automatically. The full report is emailed when the run completes.</p></body>')

    @app.get("/runs/{run_id}/manifest.json")
    def run_manifest(run_id: str):
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "unknown run")
        return repro_mod.manifest(run)

    @app.get("/runs/{run_id}/verify.json")
    def run_verify(run_id: str):
        if not store.get_run(run_id):
            raise HTTPException(404, "unknown run")
        return repro_mod.verify(store, run_id)

    @app.get("/runs/{run_id}/capsule.json")
    def run_capsule(run_id: str):
        c = repro_mod.capsule(store, run_id)
        if not c:
            raise HTTPException(404, "unknown run")
        return c

    @app.get("/runs/{run_id}/daly.json")
    def run_daly_json(run_id: str):
        rep = daly_mod.daly_report(store, run_id)
        if not rep:
            raise HTTPException(404, "no completed run with that id")
        return rep

    @app.get("/runs/{run_id}/daly", response_class=HTMLResponse)
    def run_daly_html(run_id: str):
        rep = daly_mod.daly_report(store, run_id)
        if not rep:
            raise HTTPException(404, "no completed run with that id")
        return HTMLResponse(daly_mod.render_html(rep))

    @app.get("/runs/{run_id}/daly.svg")
    def run_daly_svg(run_id: str):
        rep = daly_mod.daly_report(store, run_id)
        if not rep:
            raise HTTPException(404, "no completed run with that id")
        svg = daly_mod.density_svg(rep["hist"], rep["dalys_per_1000_conversations"])
        return Response(svg, media_type="image/svg+xml")

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

    # -- AI advice as an exposure: epidemiologic effect measures ------------
    def _epi(runs: str, ref: str, baseline, prevalence, se, sp, seed: int, judge: str = "auto") -> dict:
        ids = _run_ids(runs)
        if judge not in ("auto", "assumed"):
            raise HTTPException(400, "judge must be 'auto' (measure from adjudication) or 'assumed'")
        if ref and ref not in ids:
            raise HTTPException(400, "ref must be one of the runs")
        for name, v, lo, hi in (("baseline", baseline, 0.0, 1.0), ("prevalence", prevalence, 0.0, 1.0),
                                ("se", se, 0.0, 1.0), ("sp", sp, 0.0, 1.0)):
            if v is not None and not (lo < v <= hi if name == "baseline" else lo <= v <= hi):
                raise HTTPException(400, f"{name} must be in ({lo}, {hi}]")
        return epi_mod.exposure_analysis(store, ids, ref=ref or None, baseline=baseline,
                                         prevalence=prevalence, se=se, sp=sp, seed=seed, judge=judge)

    @app.get("/epi", response_class=HTMLResponse)
    def epi_html(runs: str = Query(...), ref: str = "", baseline: float | None = None,
                 prevalence: float | None = None, se: float | None = None, sp: float | None = None,
                 seed: int = 0, judge: str = "auto"):
        return HTMLResponse(epi_mod.render_html(_epi(runs, ref, baseline, prevalence, se, sp, seed, judge)))

    @app.get("/epi.json")
    def epi_json(runs: str = Query(...), ref: str = "", baseline: float | None = None,
                 prevalence: float | None = None, se: float | None = None, sp: float | None = None,
                 seed: int = 0, judge: str = "auto"):
        return _epi(runs, ref, baseline, prevalence, se, sp, seed, judge)

    @app.get("/epi.svg")
    def epi_svg(runs: str = Query(...), ref: str = "", baseline: float | None = None,
                prevalence: float | None = None, se: float | None = None, sp: float | None = None,
                seed: int = 0, judge: str = "auto", kind: str = "forest"):
        res = _epi(runs, ref, baseline, prevalence, se, sp, seed, judge)
        svg = epi_mod.hazard_svg(res) if kind == "hazard" else epi_mod.forest_svg(res)
        return Response(svg, media_type="image/svg+xml")

    # -- target trial emulation + causal diagrams ----------------------------
    def _tt(runs: str, ref: str) -> dict:
        ids = _run_ids(runs)
        if ref and ref not in ids:
            raise HTTPException(400, "ref must be one of the runs")
        return tt_mod.emulate(store, ids, ref=ref or None)

    @app.get("/target-trial", response_class=HTMLResponse)
    def target_trial_html(runs: str = Query(...), ref: str = ""):
        return HTMLResponse(tt_mod.render_html(_tt(runs, ref)))

    @app.get("/target-trial.json")
    def target_trial_json(runs: str = Query(...), ref: str = ""):
        return _tt(runs, ref)

    # -- Table 1: case-mix by agent + standardized mean differences -----------
    def _table1(runs: str, ref: str) -> dict:
        ids = _run_ids(runs)
        if ref and ref not in ids:
            raise HTTPException(400, "ref must be one of the runs")
        return table1_mod.table1(store, ids, ref=ref or None)

    @app.get("/table1", response_class=HTMLResponse)
    def table1_html(runs: str = Query(...), ref: str = ""):
        return HTMLResponse(table1_mod.render_html(_table1(runs, ref)))

    @app.get("/table1.json")
    def table1_json(runs: str = Query(...), ref: str = ""):
        return _table1(runs, ref)

    # -- STROBE-style reporting checklist ------------------------------------
    @app.get("/strobe", response_class=HTMLResponse)
    def strobe_html(runs: str = Query(...)):
        return HTMLResponse(strobe_mod.render_html(strobe_mod.checklist(store, _run_ids(runs))))

    @app.get("/strobe.json")
    def strobe_json(runs: str = Query(...)):
        return strobe_mod.checklist(store, _run_ids(runs))

    @app.get("/target-trial.svg")
    def target_trial_svg(design: str = "trial"):
        if design not in ("trial", "observational"):
            raise HTTPException(400, "design must be 'trial' or 'observational'")
        return Response(causal_mod.dag_svg(causal_mod.analyze(design)), media_type="image/svg+xml")

    # -- public safety leaderboard (auto-populated from every run) ----------
    @app.get("/leaderboard", response_class=HTMLResponse)
    def leaderboard_html(category: str = ""):
        return HTMLResponse(lb_mod.render_html(lb_mod.board(store, category or None)))

    @app.get("/leaderboard.json")
    def leaderboard_json(category: str = ""):
        return lb_mod.board(store, category or None)

    # -- shareable safety card / eval card / datasheet ----------------------
    @app.get("/card", response_class=HTMLResponse)
    def card_html(run: str = Query(...)):
        c = card_mod.safety_card(store, run)
        if not c:
            raise HTTPException(404, "no completed run with that id")
        return HTMLResponse(card_mod.render_card_html(c))

    @app.get("/card/{run_id}/image.svg")
    def card_image(run_id: str):
        c = card_mod.safety_card(store, run_id)
        if not c:
            raise HTTPException(404, "no completed run with that id")
        return Response(card_mod.render_card_svg(c), media_type="image/svg+xml")

    @app.get("/eval-card", response_class=HTMLResponse)
    def eval_card():
        return HTMLResponse(card_mod.render_eval_card())

    @app.get("/datasheet", response_class=HTMLResponse)
    def datasheet():
        return HTMLResponse(card_mod.render_datasheet())

    # -- ablation & baselines (research Phase E) ----------------------------
    @app.post("/ablation")
    def ablation_submit(body: AblationIn, request: Request):
        ip = request.client.host if request.client else "?"
        if not submit_limiter.allow(ip):
            raise HTTPException(429, "too many submissions from this address; try again later")
        keys = body.arms or abl_mod.arm_keys()
        unknown = [k for k in keys if k not in abl_mod.ARMS_BY_KEY]
        if unknown:
            raise HTTPException(400, f"unknown ablation arms: {', '.join(unknown)}")

        target = TargetConfig(**body.target.model_dump())
        base = {k: v for k, v in body.model_dump().items() if k not in ("target", "arms")}
        ablation_id = uuid.uuid4().hex[:12]
        arm_specs = abl_mod.expand(base, ablation_id, keys)
        specs = []
        for s in arm_specs:
            spec = RunSpec(**s)
            try:
                spec.validate(settings)
            except ValueError as exc:
                raise HTTPException(400, f"arm {s['ablation_arm']}: {exc}")
            specs.append(spec)
        try:
            validate_config(target)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        total = sum(s.n_trials for s in specs)
        try:
            store.reserve_trials(body.email, total, settings.free_trial_limit)
        except QuotaExceeded as exc:
            raise HTTPException(402, str(exc))
        try:
            if target.url:
                check_url(target.url, settings.allow_private_targets)
        except (ValueError, UnsafeTarget) as exc:
            store.refund_trials(body.email, total)
            raise HTTPException(400, str(exc))

        runs = []
        for spec in specs:
            price = round(spec.n_trials * settings.price_per_trial_usd, 2)
            run_id = store.create_run(spec.email, spec.n_trials, spec.public_dict(settings),
                                      target.public_dict(), price)
            queue.submit(run_id, spec, target)
            runs.append({"arm": spec.ablation_arm, "run_id": run_id})
        return {"ablation_id": ablation_id, "n_arms": len(runs), "runs": runs,
                "report": f"/ablation/{ablation_id}"}

    @app.get("/ablation/{ablation_id}.json")
    def ablation_json(ablation_id: str):
        return abl_mod.analyze(store, store.runs_for_ablation(ablation_id))

    @app.get("/ablation/{ablation_id}", response_class=HTMLResponse)
    def ablation_html(ablation_id: str):
        run_ids = store.runs_for_ablation(ablation_id)
        if not run_ids:
            raise HTTPException(404, "unknown ablation set")
        return HTMLResponse(abl_mod.render_html(abl_mod.analyze(store, run_ids)))

    @app.get("/ablation", response_class=HTMLResponse)
    def ablation_adhoc(runs: str = Query(...)):
        return HTMLResponse(abl_mod.render_html(abl_mod.analyze(store, _run_ids(runs))))

    # -- field scan: run the whole field of health-advice agents -------------
    @app.post("/field")
    def field_submit(body: FieldScanIn, request: Request):
        ip = request.client.host if request.client else "?"
        if not submit_limiter.allow(ip):
            raise HTTPException(429, "too many submissions from this address; try again later")
        runnable, skipped = field_mod.available_panel(settings)
        if body.models:
            unknown = [m for m in body.models if m not in field_mod.PANEL_BY_KEY]
            if unknown:
                raise HTTPException(400, f"unknown panel models: {', '.join(unknown)}")
            runnable = [p for p in runnable if p["key"] in body.models]
        if not runnable:
            raise HTTPException(400, "no panel providers have server-side keys configured; "
                                     "set provider keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, …)")
        field_id = uuid.uuid4().hex[:12]
        seed = body.seed or 20260101  # pin a seed so the case-mix is shared across agents
        specs, targets = [], []
        for entry in runnable:
            spec = RunSpec(email=body.email, n_trials=body.n_trials, specialty=body.specialty,
                           condition=body.condition, seed=seed, max_turns=body.max_turns,
                           harm_threshold=body.harm_threshold, orchestration=body.orchestration,
                           judges=body.judges, field_scan_id=field_id)
            target = TargetConfig(**field_mod.target_for(entry, settings))
            try:
                spec.validate(settings)
                validate_config(target)
            except ValueError as exc:
                raise HTTPException(400, f"{entry['display']}: {exc}")
            specs.append(spec)
            targets.append((entry, target))
        total = sum(s.n_trials for s in specs)
        try:
            store.reserve_trials(body.email, total, settings.free_trial_limit)
        except QuotaExceeded as exc:
            raise HTTPException(402, str(exc))
        runs = []
        for spec, (entry, target) in zip(specs, targets):
            price = round(spec.n_trials * settings.price_per_trial_usd, 2)
            run_id = store.create_run(spec.email, spec.n_trials, spec.public_dict(settings),
                                      target.public_dict(), price)
            queue.submit(run_id, spec, target)
            runs.append({"model": entry["key"], "display": entry["display"], "run_id": run_id})
        return {"field_id": field_id, "n_models": len(runs), "runs": runs,
                "skipped": [{"display": s["display"], "reason": s["reason"]} for s in skipped],
                "report": f"/field?field={field_id}"}

    def _field_ids(field: str, runs: str) -> list[str]:
        if field:
            return store.runs_for_field(field)
        if runs:
            return _run_ids(runs)
        raise HTTPException(400, "provide ?field=<id> or ?runs=<id>,<id>,…")

    @app.get("/field", response_class=HTMLResponse)
    def field_html(field: str = "", runs: str = ""):
        return HTMLResponse(field_mod.render_html(field_mod.field_results(store, _field_ids(field, runs))))

    @app.get("/field.json")
    def field_json(field: str = "", runs: str = ""):
        return field_mod.field_results(store, _field_ids(field, runs))

    @app.get("/field.svg")
    def field_svg(field: str = "", runs: str = "", share: int = 0):
        res = field_mod.field_results(store, _field_ids(field, runs))
        svg = field_mod.share_svg(res) if share else field_mod.harm_chart_svg(res)
        return Response(svg, media_type="image/svg+xml")

    # -- grader (judge) bias & robustness audit -----------------------------
    def _run_grader_audit(audit_id: str, judges: list[str], threshold: float):
        try:
            store.update_grader_audit(audit_id, status="running")
            models = {s: build_model(s, settings, runner.mocks) for s in judges}
            scorer = gaudit.build_scorer(models)
            result = gaudit.run_audit(scorer, judges, threshold=threshold)
            store.update_grader_audit(audit_id, status="complete", result=result,
                                      report_html=gaudit.render_html(result))
        except Exception as exc:  # the audit worker must fail cleanly
            store.update_grader_audit(audit_id, status="failed", error=str(exc)[:500])

    @app.post("/grader-audit")
    def grader_audit_submit(body: GraderAuditIn, request: Request):
        ip = request.client.host if request.client else "?"
        if not submit_limiter.allow(ip):
            raise HTTPException(429, "too many submissions from this address; try again later")
        judges = body.judges or list(settings.default_judges)
        try:
            for spec in judges:
                parse_spec(spec)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not 0.0 < body.threshold < 1.0:
            raise HTTPException(400, "threshold must be between 0 and 1")
        audit_id = store.create_grader_audit({"judges": judges, "threshold": body.threshold})
        audit_pool.submit(_run_grader_audit, audit_id, judges, body.threshold)
        return {"audit_id": audit_id, "poll": f"/grader-audit/{audit_id}.json",
                "report": f"/grader-audit/{audit_id}"}

    @app.get("/grader-audit/{audit_id}.json")
    def grader_audit_json(audit_id: str):
        a = store.get_grader_audit(audit_id)
        if not a:
            raise HTTPException(404, "unknown audit")
        return {"audit_id": audit_id, "status": a["status"], "error": a["error"],
                "spec": a["spec"], "result": a["result"]}

    @app.get("/grader-audit/{audit_id}", response_class=HTMLResponse)
    def grader_audit_report(audit_id: str):
        a = store.get_grader_audit(audit_id)
        if not a:
            raise HTTPException(404, "unknown audit")
        if a["status"] == "complete" and a["report_html"]:
            return HTMLResponse(a["report_html"])
        msg = {"queued": "Queued.", "running": "Running the grader audit…",
               "failed": f"Failed: {a['error']}"}.get(a["status"], a["status"])
        refresh = "" if a["status"] == "failed" else '<meta http-equiv="refresh" content="4">'
        return HTMLResponse(
            f'<!doctype html><meta charset=utf-8>{refresh}<title>Grader audit {audit_id}</title>'
            f'<body style="font:16px system-ui;max-width:640px;margin:60px auto;padding:0 16px">'
            f'<h1>Grader bias &amp; robustness audit</h1><p>{msg}</p>'
            f'<p style="color:#666">This page refreshes automatically.</p></body>')

    @app.get("/adjudicate/{set_id}", response_class=HTMLResponse)
    def adjudicate_ui(set_id: str):
        if not store.get_adjudication_set(set_id):
            raise HTTPException(404, "unknown adjudication set")
        f = STATIC / "adjudicate.html"
        return HTMLResponse(f.read_text() if f.exists() else "<h1>adjudication</h1>")

    # -- Critical Harm Event (CHE) measurement -----------------------------

    def _build_model(spec: str):
        return (runner.model_factory(spec, settings, runner.mocks)
                if runner.mocks is not None else runner.model_factory(spec, settings))

    @app.post("/runs/{run_id}/che/screen")
    def che_screen(run_id: str, body: CheScreenIn):
        if not settings.che_enabled:
            raise HTTPException(400, "CHE measurement is disabled (REDTEAM_CHE_ENABLED)")
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "unknown run")
        cfg = run["config"]
        attackers = (cfg.get("orchestration") or {}).get("attackers") or []
        spec = body.screener_model.strip() or settings.che_screener_model
        try:
            che_screener.assert_screener_distinct(spec, attackers)
            model = _build_model(spec)
        except (che_screener.ScreenerModelConflict, Exception) as exc:
            if isinstance(exc, che_screener.ScreenerModelConflict):
                raise HTTPException(400, str(exc))
            raise HTTPException(400, f"could not build screener model {spec!r}: {exc}")
        versions = {"attacker": ",".join(attackers), "target": dataset.target_label(run), "screener": spec}
        screener = che_screener.CheScreener(spec, model, settings.che_screen_threshold, versions)
        n = 0
        for t in store.trials_for_run(run_id):
            from .personas import Persona
            persona = Persona(**t["persona"])
            history: list[dict] = []
            for u in t["turns"]:
                history.append({"role": "user", "content": u["user_message"]})
                fields = screener.screen(persona, list(history), u["target_reply"])
                store.upsert_che_label({
                    "run_id": run_id, "turn_id": u["id"], "trial_id": t["id"],
                    "rater_type": "llm_screener", "rater_id": spec, "turn_index": u["idx"],
                    "model_versions": versions, "sample_source": "representative",
                    "inclusion_prob": 1.0, **fields})
                history.append({"role": "assistant", "content": u["target_reply"]})
                n += 1
        return {"run_id": run_id, "screened": n, "screener_model": spec}

    @app.post("/che/review-sets")
    def che_review_set(body: CheReviewSetIn):
        run_ids = [r.strip() for r in body.run_ids if r.strip()]
        if not run_ids:
            raise HTTPException(400, "at least one run_id is required")
        labels = []
        for rid in run_ids:
            if not store.get_run(rid):
                raise HTTPException(404, f"unknown run {rid}")
            labels.extend(store.che_labels(rid, rater_type="llm_screener"))
        if not labels:
            raise HTTPException(400, "no screener labels yet — run POST /runs/<id>/che/screen first")
        rate = settings.che_neg_sample_rate if body.neg_sample_rate is None else body.neg_sample_rate
        selected = che_review.select_two_phase(labels, neg_sample_rate=rate, seed=body.seed)
        # blinded context: persona brief + conversation up to the scored turn + full reply
        turn_ctx = {}
        for rid in run_ids:
            for t in store.trials_for_run(rid):
                hist = []
                for u in t["turns"]:
                    hist.append({"role": "user", "content": u["user_message"]})
                    turn_ctx[u["id"]] = {"persona_brief": adj._persona_brief(t["persona"]),
                                         "conversation_before": list(hist), "reply": u["target_reply"]}
                    hist.append({"role": "assistant", "content": u["target_reply"]})
        items = [{"turn_id": s.turn_id, "run_id": s.run_id, "pathway": s.pathway,
                  "screen_positive": s.screen_positive, "inclusion_prob": s.inclusion_prob,
                  "sample_source": s.sample_source, "sampling_weight": s.sampling_weight,
                  "context": turn_ctx.get(s.turn_id, {"reply": ""})} for s in selected]
        spec = {"neg_sample_rate": rate, "seed": body.seed}
        set_id = store.create_che_review_set(body.name.strip() or f"CHE review of {len(run_ids)} run(s)",
                                             spec, run_ids, items)
        base = settings.public_base_url.rstrip("/")
        return {"set_id": set_id, "n_items": len(items),
                "n_screen_positive": sum(1 for s in selected if s.screen_positive),
                "label_url": f"{base}/che-review/{set_id}"}

    @app.get("/che-review/{set_id}/items")
    def che_review_items(set_id: str):
        s = store.get_che_review_set(set_id)
        if not s:
            raise HTTPException(404, "unknown CHE review set")
        return {"set_id": set_id, "name": s["name"], "n_items": s["n_items"],
                "pathways": list(che.PATHWAYS), "likelihood": list(che.LIKELIHOOD),
                "che_severity": che.CHE_SEVERITY, "items": store.che_review_items(set_id, blinded=True)}

    @app.post("/che-review/{set_id}/items/{item_id}/label")
    def che_review_label(set_id: str, item_id: int, body: CheLabelIn):
        s = store.get_che_review_set(set_id)
        if not s:
            raise HTTPException(404, "unknown CHE review set")
        if body.rater_type not in che.RATER_TYPES or body.rater_type == "llm_screener":
            raise HTTPException(400, "rater_type must be clinician_1, clinician_2, or adjudicator")
        if not 0 <= body.severity <= 5:
            raise HTTPException(400, "severity must be 0–5")
        if body.likelihood not in che.LIKELIHOOD or body.pathway not in che.PATHWAYS:
            raise HTTPException(400, "invalid likelihood or pathway")
        item = next((it for it in store.che_review_items(set_id, blinded=False) if it["id"] == item_id), None)
        if not item:
            raise HTTPException(404, "unknown item")
        derived = che.derive_che(body.severity, body.life_threatening, body.likelihood, body.actionable)
        store.upsert_che_label({
            "run_id": item["run_id"], "turn_id": item["turn_id"], "rater_type": body.rater_type,
            "rater_id": body.rater.strip() or body.rater_type, "severity": body.severity,
            "life_threatening": body.life_threatening, "likelihood": body.likelihood,
            "actionable": body.actionable, "pathway": body.pathway, "che": derived,
            "rationale": body.rationale.strip()[:1200], "sample_source": item["sample_source"],
            "sampling_weight": item["sampling_weight"], "inclusion_prob": item["inclusion_prob"],
            "screen_positive": item["screen_positive"], "model_versions": {}})
        return {"ok": True, "che": derived}

    @app.get("/che-review/{set_id}", response_class=HTMLResponse)
    def che_review_ui(set_id: str):
        if not store.get_che_review_set(set_id):
            raise HTTPException(404, "unknown CHE review set")
        f = STATIC / "che_review.html"
        return HTMLResponse(f.read_text() if f.exists() else "<h1>CHE review</h1>")

    @app.get("/che/report", response_class=HTMLResponse)
    def che_report_html(runs: str = Query(...)):
        ids = _run_ids(runs)
        return HTMLResponse(che_report.render_che_html(che_report.che_report_json(store, ids, settings), ids))

    @app.get("/che.json")
    def che_report_json_ep(runs: str = Query(...)):
        return che_report.che_report_json(store, _run_ids(runs), settings)

    # -- sample-size / power planning (research §4) -------------------------

    @app.get("/power.json")
    def power_json(mode: str = "precision", p: float = 0.1, half_width: float = 0.03,
                   p1: float = 0.3, p2: float = 0.1, alpha: float = 0.05, power: float = 0.8,
                   n_per_group: int = 0, cluster_size: float = 1.0, icc: float = 0.0,
                   n_valid: int = 1000, screen_positive_rate: float = 0.05,
                   neg_sample_rate: float = 0.10, target_upper: float = 0.01):
        de = power_mod.design_effect(cluster_size, icc)
        try:
            if mode == "precision":
                out = power_mod.n_for_precision(p, half_width, design_effect=de)
            elif mode == "two_proportions":
                out = power_mod.n_two_proportions(p1, p2, alpha, power, design_effect=de)
            elif mode == "mde":
                if n_per_group <= 0:
                    raise ValueError("n_per_group is required for mode=mde")
                out = power_mod.min_detectable_difference(p1, n_per_group, alpha, power, design_effect=de)
            elif mode == "review_burden":
                out = power_mod.two_phase_review_burden(n_valid, screen_positive_rate, neg_sample_rate)
            elif mode == "rule_of_three":
                out = power_mod.rule_of_three_n(target_upper)
            else:
                raise ValueError("mode must be precision, two_proportions, mde, review_burden, or rule_of_three")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"mode": mode, "design_effect": de, **out}

    @app.get("/power", response_class=HTMLResponse)
    def power_ui():
        f = STATIC / "power.html"
        return HTMLResponse(f.read_text() if f.exists() else "<h1>power calculator</h1>")

    @app.get("/guide", response_class=HTMLResponse)
    def guide_page():
        runnable, _ = field_mod.available_panel(settings)
        return HTMLResponse(guide_mod.render_html(available_models={p["key"] for p in runnable}))

    @app.get("/runs.json")
    def runs_list(limit: int = 200):
        """Recent runs for the workflow launchers' run pickers (no secrets, masked email)."""
        out = []
        for r in store.recent_runs(min(max(limit, 1), 500)):
            cfg = r.get("config") or {}
            label = dataset.target_label({"target": r.get("target") or {}, "config": cfg})
            out.append({"run_id": r["id"], "status": r["status"], "created_at": r["created_at"],
                        "n_trials": r["n_trials"], "completed_trials": r["completed_trials"],
                        "label": field_mod._MODEL_DISPLAY.get(label, label),
                        "specialty": cfg.get("specialty"), "condition": cfg.get("condition"),
                        "seed": cfg.get("seed"), "email": _mask(r["email"]),
                        "field_scan_id": cfg.get("field_scan_id") or "", "ablation_id": cfg.get("ablation_id") or ""})
        return {"n": len(out), "runs": out}

    _STATIC_OK = {"ui.css": "text/css", "guide.js": "application/javascript"}

    @app.get("/static/{name}")
    def static_asset(name: str):
        if name not in _STATIC_OK or not (STATIC / name).exists():
            raise HTTPException(404, "no such asset")
        # revalidate on every load (ETag/Last-Modified make it cheap) so a restyle never needs a hard refresh
        return FileResponse(STATIC / name, media_type=_STATIC_OK[name], headers={"Cache-Control": "no-cache"})

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
