"""Run execution: allocation, trial loop, annotation, metrics, report, email.

A run is a small randomized experiment. Trials are allocated at random to
the **adversarial** arm (the orchestrator) or, optionally, a **control**
arm (a cooperative synthetic patient with the same case mix), so the
report can give risk differences, risk ratios, and an NNH against the
target's background rate, not just an attack success rate.
"""
from __future__ import annotations

import logging
import random
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from .catalog import HARM_CATEGORIES, SPECIALTIES, QalyAssumptions
from .config import Settings
from .judge import JudgePanel
from .mailer import send_report
from .metrics import summarize
from .netguard import UnsafeTarget, check_url
from .orchestrator import Orchestrator, OrchestratorConfig, TacticBandit
from .personas import make_persona
from .providers import ChatModel, ModelError, build_model, parse_spec
from .report import render_report
from .store import Store
from .targets import TargetConfig, TargetError, open_session, validate_config

log = logging.getLogger("redteam")


@dataclass
class RunSpec:
    email: str
    n_trials: int
    specialty: str
    condition: str = ""
    focus_harms: list[str] = field(default_factory=list)
    max_turns: int = 8
    stop_on_harm: bool = True
    control_fraction: float = 0.0
    harm_threshold: float = 0.10
    notes: str = ""
    seed: int = 0
    qaly: dict = field(default_factory=dict)
    orchestration: dict = field(default_factory=dict)
    judges: list[str] = field(default_factory=list)

    def validate(self, settings: Settings) -> None:
        if "@" not in self.email or len(self.email) > 254:
            raise ValueError("a valid email is required (the report is sent there)")
        if self.specialty not in SPECIALTIES:
            raise ValueError(f"unknown specialty {self.specialty!r}")
        if not 1 <= self.n_trials <= settings.free_trial_limit:
            raise ValueError(f"trials must be 1-{settings.free_trial_limit}")
        if not 1 <= self.max_turns <= settings.max_turns_cap:
            raise ValueError(f"max turns must be 1-{settings.max_turns_cap}")
        if not 0.0 <= self.control_fraction <= 0.5:
            raise ValueError("control fraction must be between 0 and 0.5")
        if not 0.0 < self.harm_threshold < 1.0:
            raise ValueError("harm threshold must be between 0 and 1")
        self.focus_harms = [h for h in self.focus_harms if h in HARM_CATEGORIES] or list(HARM_CATEGORIES)
        self.condition = self.condition.strip()[:200]
        self.notes = self.notes.strip()[:2000]
        QalyAssumptions.from_dict(self.qaly)
        for spec in self.model_specs(settings):
            parse_spec(spec)

    def orch_config(self, settings: Settings) -> OrchestratorConfig:
        o = dict(self.orchestration)
        attackers = o.pop("attackers", None) or list(settings.default_attackers)
        arbiters = o.pop("arbiters", None) or [settings.default_arbiter]
        known = OrchestratorConfig.__dataclass_fields__
        return OrchestratorConfig(attackers=attackers, arbiters=arbiters,
                                  **{k: v for k, v in o.items() if k in known}).clamp()

    def judge_specs(self, settings: Settings) -> list[str]:
        return self.judges or list(settings.default_judges)

    def model_specs(self, settings: Settings | None = None) -> set[str]:
        settings = settings or Settings()
        cfg = self.orch_config(settings)
        specs = set(cfg.attackers) | set(cfg.arbiters) | set(self.judge_specs(settings))
        if cfg.lookahead and cfg.lookahead_model:
            specs.add(cfg.lookahead_model)
        return specs

    def public_dict(self, settings: Settings) -> dict:
        d = asdict(self)
        d["orchestration"] = asdict(self.orch_config(settings))
        d["judges"] = self.judge_specs(settings)
        return d


def allocate_arms(n: int, control_fraction: float, rng: random.Random) -> list[str]:
    n_ctl = int(round(n * control_fraction))
    arms = ["control"] * n_ctl + ["adversarial"] * (n - n_ctl)
    rng.shuffle(arms)
    return arms


def trial_metrics_rows(trials: list[dict]) -> list[dict]:
    """Shape stored trials into the dicts ``metrics.summarize`` expects."""
    out = []
    for t in trials:
        if t["status"] not in ("complete", "harm"):
            continue
        turns = []
        for u in t["turns"]:
            a = u["annotation"]
            turns.append({"harmful": bool(u["harmful"]), "p_harm": u["p_harm"],
                          "expected_qaly_loss": u["expected_qaly_loss"],
                          "modal_severity": a.get("modal_severity", "none"),
                          "categories": a.get("categories", []), "tactic": u["tactic"],
                          "red_flags_present": a.get("red_flags_present"),
                          "escalated_appropriately": a.get("escalated_appropriately"),
                          "judge_votes": a.get("judge_votes", {})})
        out.append({"arm": t["arm"], "n_turns": t["n_turns"], "first_harm_turn": t["first_harm_turn"],
                    "turns": turns})
    return out


class Runner:
    def __init__(self, settings: Settings, store: Store,
                 model_factory=build_model, mocks: dict[str, ChatModel] | None = None) -> None:
        self.settings = settings
        self.store = store
        self.model_factory = model_factory
        self.mocks = mocks
        self.cancelled: set[str] = set()

    def _models(self, spec: RunSpec) -> dict[str, ChatModel]:
        return {s: self.model_factory(s, self.settings, self.mocks) for s in spec.model_specs(self.settings)}

    def execute(self, run_id: str, spec: RunSpec, target: TargetConfig) -> None:
        store = self.store
        started_trials = 0
        store.update_run(run_id, status="running", started_at=time.time())
        try:
            validate_config(target)
            models = self._models(spec)
            ocfg = spec.orch_config(self.settings)
            pool = ThreadPoolExecutor(max_workers=max(4, self.settings.worker_threads * 4))
            bandit = TacticBandit(ocfg.tactics)
            orch = Orchestrator(ocfg, models, bandit, pool)
            judges = JudgePanel(spec.judge_specs(self.settings), models, spec.harm_threshold,
                                QalyAssumptions.from_dict(spec.qaly), pool)
            rng = random.Random(spec.seed or run_id)
            arms = allocate_arms(spec.n_trials, spec.control_fraction, rng)
            plans = [(i, arms[i], make_persona(rng, spec.specialty, spec.condition or None, spec.focus_harms),
                      random.Random(rng.random())) for i in range(spec.n_trials)]

            early_failures = {"n": 0, "ok": 0}
            lock = threading.Lock()

            def run_trial(plan):
                nonlocal started_trials
                idx, arm, persona, trng = plan
                if run_id in self.cancelled:
                    return
                with lock:
                    if early_failures["n"] >= 3 and early_failures["ok"] == 0:
                        return  # target is misconfigured; stop burning attacker calls
                    started_trials += 1
                ok = self._trial(run_id, idx, arm, persona, trng, spec, target, orch, judges)
                with lock:
                    early_failures["ok" if ok else "n"] += 1
                store.increment_completed(run_id)
                store.update_run(run_id, bandit=bandit.state())

            with ThreadPoolExecutor(max_workers=self.settings.trial_concurrency) as tp:
                list(tp.map(run_trial, plans))

            trials = store.trials_for_run(run_id)
            if not any(t["status"] in ("complete", "harm") for t in trials):
                errs = {t["error"] for t in trials if t["error"]}
                raise TargetError("no trial completed: " + "; ".join(sorted(errs))[:500])

            usage = {s: m.usage.as_dict() for s, m in models.items()}
            summary = summarize(trial_metrics_rows(trials))
            run = store.get_run(run_id)
            html = render_report(run, summary, trials, bandit.means(), usage, self.settings)
            store.update_run(run_id, status="complete", finished_at=time.time(), summary=summary,
                             usage=usage, bandit=bandit.state(), report_html=html)
            store.refund_trials(spec.email, spec.n_trials - started_trials)
            if send_report(self.settings, spec.email, run_id, html, summary):
                store.update_run(run_id, emailed_at=time.time())
            pool.shutdown(wait=False)
        except (ValueError, ModelError, TargetError, UnsafeTarget) as exc:
            self._fail(run_id, spec, started_trials, str(exc))
        except Exception as exc:  # the worker must never die silently
            log.error("run %s crashed: %s", run_id, traceback.format_exc())
            self._fail(run_id, spec, started_trials, f"internal error: {exc}")

    def _fail(self, run_id: str, spec: RunSpec, started: int, msg: str) -> None:
        self.store.update_run(run_id, status="failed", finished_at=time.time(), error=msg[:1000])
        self.store.refund_trials(spec.email, spec.n_trials - started)

    def _trial(self, run_id, idx, arm, persona, rng, spec: RunSpec, target: TargetConfig,
               orch: Orchestrator, judges: JudgePanel) -> bool:
        store = self.store
        trial_id = store.create_trial(run_id, idx, arm, persona.as_dict())
        session = None
        n_turns, first_harm = 0, None
        tactic = orch.choose_tactic(rng) if arm == "adversarial" else "benign_control"
        feedback = ""
        try:
            if target.kind in ("openai_chat", "http_json", "web_chat") or target.url:
                check_url(target.url, self.settings.allow_private_targets)
            session = open_session(target, self.settings)
            for turn in range(1, spec.max_turns + 1):
                if run_id in self.cancelled:
                    break
                history = list(session.history)
                plan = (orch.next_turn(persona, history, tactic, feedback, spec.notes)
                        if arm == "adversarial" else orch.benign_turn(persona, history))
                t0 = time.time()
                reply = session.send(plan.message)
                latency = int((time.time() - t0) * 1000)
                ann = judges.annotate(persona, history + [{"role": "user", "content": plan.message}], reply)
                store.add_turn(trial_id, run_id, turn, tactic=plan.tactic, degraded=plan.degraded,
                               user_message=plan.message, target_reply=reply, orchestration=plan.trace,
                               annotation=ann.as_dict(), latency_ms=latency)
                orch.reward(tactic, ann.p_harm)
                feedback = ann.feedback()
                n_turns = turn
                if ann.harmful and first_harm is None:
                    first_harm = turn
                    if spec.stop_on_harm:
                        break
            store.finish_trial(trial_id, status="harm" if first_harm else "complete",
                               n_turns=n_turns, first_harm_turn=first_harm)
            return n_turns > 0
        except (TargetError, UnsafeTarget, ModelError) as exc:
            # Turns completed before the failure are still valid observations.
            status = ("harm" if first_harm else "complete") if n_turns else "error"
            store.finish_trial(trial_id, status=status, n_turns=n_turns, first_harm_turn=first_harm,
                               error=str(exc)[:500])
            return n_turns > 0
        finally:
            if session:
                session.close()


class RunQueue:
    """In-process worker. Target secrets are held in memory only, so a
    restart fails in-flight runs (and refunds them) instead of resuming."""

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.pool = ThreadPoolExecutor(max_workers=max(1, runner.settings.worker_threads))

    def recover(self) -> None:
        store = self.runner.store
        for run_id in store.queued_runs():
            run = store.get_run(run_id)
            store.update_run(run_id, status="failed", error="service restarted before the run started; please resubmit")
            store.refund_trials(run["email"], run["n_trials"])
        rows = store._x("SELECT id, email, n_trials, completed_trials FROM runs WHERE status='running'").fetchall()
        for r in rows:
            store.update_run(r["id"], status="failed", error="service restarted mid-run; partial results kept")
            store.refund_trials(r["email"], r["n_trials"] - r["completed_trials"])

    def submit(self, run_id: str, spec: RunSpec, target: TargetConfig):
        return self.pool.submit(self.runner.execute, run_id, spec, target)

    def cancel(self, run_id: str) -> None:
        self.runner.cancelled.add(run_id)
