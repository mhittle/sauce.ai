"""Tidy dataset export (RESEARCH.md Phase B).

Flattens stored runs/trials/turns into analysis-ready long tables — one row
per turn (the response-level unit) and one row per conversation (the trial-
level unit) — carrying every covariate the statistical analysis plan needs
(§5): arm, specialty, persona attributes, tactic, time index, the judge's
verdict, and the run's protocol knobs (seed, threshold, ensembles). Written
so the same seed + specialty + n_trials across target runs yields the same
persona case-mix, enabling a paired cross-model analysis.

Pure stdlib (uses csv for serialization); no Flask, no DB.
"""
from __future__ import annotations

import csv
import io

TURN_COLUMNS = [
    "run_id", "target_label", "arm", "trial_idx", "trial_id", "trial_status",
    "specialty", "condition", "persona_age", "persona_sex", "persona_speaker",
    "persona_literacy", "persona_affect", "persona_access", "persona_focus_harm",
    "persona_red_flag", "tactic", "degraded", "turn_idx", "n_turns_in_trial",
    "first_harm_turn", "is_first_harm", "p_harm", "harmful", "modal_severity",
    "categories", "n_categories", "red_flags_present", "escalated_appropriately",
    "expected_qaly_loss", "latency_ms", "harm_threshold", "seed",
    "attackers", "arbiters", "judges", "created_at",
]

TRIAL_COLUMNS = [
    "run_id", "target_label", "arm", "trial_idx", "trial_id", "trial_status",
    "specialty", "condition", "persona_age", "persona_sex", "persona_focus_harm",
    "n_turns", "first_harm_turn", "any_harm", "sum_expected_qaly_loss",
    "max_p_harm", "harm_categories", "harm_threshold", "seed",
]


def target_label(run: dict) -> str:
    """A short, stable label for the system under test. In a benchmark the
    researcher pins a distinct model per target run, so the model id is the
    natural label; fall back to kind + host."""
    t = run.get("target") or {}
    if t.get("model"):
        return str(t["model"])
    url = (t.get("url") or "").split("//", 1)[-1].split("/", 1)[0]
    return f"{t.get('kind', '?')}:{url}" if url else str(t.get("kind", "?"))


def _persona(t: dict) -> dict:
    return t.get("persona", {}) or {}


def turn_rows(run: dict, trials: list[dict]) -> list[dict]:
    cfg = run.get("config") or {}
    orch = cfg.get("orchestration") or {}
    label = target_label(run)
    common = {
        "run_id": run["id"], "target_label": label,
        "harm_threshold": cfg.get("harm_threshold"), "seed": cfg.get("seed"),
        "attackers": ";".join(orch.get("attackers", []) or []),
        "arbiters": ";".join(orch.get("arbiters", []) or []),
        "judges": ";".join(cfg.get("judges", []) or []),
    }
    rows = []
    for t in trials:
        p = _persona(t)
        for u in t.get("turns", []):
            a = u.get("annotation", {})
            rows.append({
                **common,
                "arm": t["arm"], "trial_idx": t["idx"], "trial_id": t["id"],
                "trial_status": t["status"],
                "specialty": p.get("specialty"), "condition": p.get("condition"),
                "persona_age": p.get("age"), "persona_sex": p.get("sex"),
                "persona_speaker": p.get("speaker"), "persona_literacy": p.get("health_literacy"),
                "persona_affect": p.get("affect"), "persona_access": p.get("access"),
                "persona_focus_harm": p.get("focus_harm"), "persona_red_flag": p.get("red_flag"),
                "tactic": u.get("tactic"), "degraded": int(bool(u.get("degraded"))),
                "turn_idx": u["idx"], "n_turns_in_trial": t["n_turns"],
                "first_harm_turn": t["first_harm_turn"],
                "is_first_harm": int(t["first_harm_turn"] == u["idx"]),
                "p_harm": u["p_harm"], "harmful": int(bool(u["harmful"])),
                "modal_severity": a.get("modal_severity"),
                "categories": ";".join(a.get("categories", []) or []),
                "n_categories": len(a.get("categories", []) or []),
                "red_flags_present": _tri(a.get("red_flags_present")),
                "escalated_appropriately": _tri(a.get("escalated_appropriately")),
                "expected_qaly_loss": u["expected_qaly_loss"], "latency_ms": u.get("latency_ms"),
                "created_at": run.get("created_at"),
            })
    return rows


def trial_rows(run: dict, trials: list[dict]) -> list[dict]:
    cfg = run.get("config") or {}
    label = target_label(run)
    rows = []
    for t in trials:
        p = _persona(t)
        turns = t.get("turns", [])
        cats = sorted({c for u in turns for c in (u.get("annotation", {}).get("categories") or [])})
        rows.append({
            "run_id": run["id"], "target_label": label, "arm": t["arm"],
            "trial_idx": t["idx"], "trial_id": t["id"], "trial_status": t["status"],
            "specialty": p.get("specialty"), "condition": p.get("condition"),
            "persona_age": p.get("age"), "persona_sex": p.get("sex"),
            "persona_focus_harm": p.get("focus_harm"),
            "n_turns": t["n_turns"], "first_harm_turn": t["first_harm_turn"],
            "any_harm": int(bool(t["first_harm_turn"])),
            "sum_expected_qaly_loss": round(sum(u["expected_qaly_loss"] for u in turns), 6),
            "max_p_harm": max((u["p_harm"] for u in turns), default=0.0),
            "harm_categories": ";".join(cats),
            "harm_threshold": cfg.get("harm_threshold"), "seed": cfg.get("seed"),
        })
    return rows


def _tri(x):
    """Serialize a nullable boolean without turning None into 'False'."""
    return "" if x is None else int(bool(x))


def to_csv(rows: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
    return buf.getvalue()


def build(store, run_ids: list[str], level: str = "turn") -> tuple[list[dict], list[str]]:
    """Collect tidy rows across runs. level: 'turn' or 'trial'."""
    rows: list[dict] = []
    for rid in run_ids:
        run = store.get_run(rid)
        if not run:
            continue
        trials = store.trials_for_run(rid)
        rows.extend(turn_rows(run, trials) if level == "turn" else trial_rows(run, trials))
    cols = TURN_COLUMNS if level == "turn" else TRIAL_COLUMNS
    return rows, cols
