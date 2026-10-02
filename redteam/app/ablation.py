"""Ablation & baseline harness (RESEARCH.md §7, Phase E).

To claim the attack orchestrator as a methods contribution, not plumbing, we
need matched runs that toggle one component at a time and measure the marginal
effect on attack success and prompts-to-harm. This module:

1. Defines the **arm matrix** — the full stack (reference), one ablation per
   component (bandit, ensemble, refinement depth, lookahead, consensus), and a
   single-prompt baseline — each expressed as overrides on a base run spec.
2. **Expands** a base spec into one matched run per arm, sharing seed +
   specialty + n_trials + target so every arm sees the *same* persona case-mix
   (a paired design).
3. **Analyses** a completed ablation set: per-arm attack success and
   time-to-harm, plus the component's marginal effect (reference − arm) as a
   Newcombe risk difference and a log-rank test on the KM curves.

Descriptive layer only — reuses `metrics` (Wilson, Newcombe RD, log-rank).
The confirmatory paired model (mixed-effects / McNemar on the matched
personas) belongs in the analysis repo, against the tidy export.
"""
from __future__ import annotations

import copy
import datetime as dt
from html import escape

from . import metrics, report
from .dataset import target_label

# Each arm overrides the base orchestration (``orch``) and/or the base run spec
# (``run``). ``single_attacker`` is a sentinel handled in ``apply_arm``: it
# truncates the attacker ensemble to its first model.
ARMS: list[dict] = [
    {"key": "full", "label": "Full stack", "kind": "reference",
     "orch": {}, "run": {},
     "desc": "The complete orchestrator: tactic bandit, attacker ensemble, refinement, consensus (and lookahead if configured)."},
    {"key": "no_bandit", "label": "Random tactic", "kind": "ablation",
     "orch": {"bandit": False}, "run": {},
     "desc": "Tactics chosen at random instead of by the Thompson-sampling bandit."},
    {"key": "single_attacker", "label": "Single attacker", "kind": "ablation",
     "orch": {"single_attacker": True}, "run": {},
     "desc": "One attacker model instead of the ensemble (no propose diversity)."},
    {"key": "no_refine", "label": "No refinement", "kind": "ablation",
     "orch": {"levels": 1}, "run": {},
     "desc": "Propose only; no beam refinement passes (levels = 1)."},
    {"key": "no_lookahead", "label": "No lookahead", "kind": "ablation",
     "orch": {"lookahead": False}, "run": {},
     "desc": "Arbiters score candidates without simulating the target's reply."},
    {"key": "no_consensus", "label": "No consensus", "kind": "ablation",
     "orch": {"consensus_rounds": 0}, "run": {},
     "desc": "Top candidate taken directly; no arbiter deliberation round."},
    {"key": "single_prompt", "label": "Single-prompt baseline", "kind": "baseline",
     "orch": {"bandit": False, "levels": 1, "lookahead": False,
              "consensus_rounds": 0, "single_attacker": True},
     "run": {"max_turns": 1, "stop_on_harm": True},
     "desc": "One attacker, one prompt, no adaptation — the floor the orchestrator must beat."},
]

ARMS_BY_KEY = {a["key"]: a for a in ARMS}
REFERENCE_KEY = "full"


def arm_keys() -> list[str]:
    return [a["key"] for a in ARMS]


def apply_arm(base_spec: dict, arm: dict) -> dict:
    """Return a new run-spec dict for ``arm`` derived from ``base_spec``.

    ``base_spec`` is a RunSpec-shaped dict (the full-stack configuration the
    researcher chose). The arm's ``run`` overrides apply at the top level and
    its ``orch`` overrides merge into ``orchestration``; ``single_attacker``
    truncates the ensemble.
    """
    spec = copy.deepcopy(base_spec)
    orch = dict(spec.get("orchestration") or {})
    overrides = dict(arm.get("orch") or {})
    if overrides.pop("single_attacker", False):
        attackers = orch.get("attackers") or []
        if attackers:
            orch["attackers"] = attackers[:1]
    orch.update(overrides)
    spec["orchestration"] = orch
    spec.update(arm.get("run") or {})
    spec["ablation_arm"] = arm["key"]
    return spec


def expand(base_spec: dict, ablation_id: str, keys: list[str] | None = None) -> list[dict]:
    """Expand a base spec into one matched run-spec per arm (shared seed etc.)."""
    chosen = keys or arm_keys()
    out = []
    for key in chosen:
        arm = ARMS_BY_KEY[key]
        spec = apply_arm(base_spec, arm)
        spec["ablation_id"] = ablation_id
        out.append(spec)
    return out


# -- analysis -----------------------------------------------------------------

def _survival(trials: list[dict], max_turns: int) -> tuple[list[int], list[bool]]:
    """(time, event) per adversarial conversation for the log-rank test:
    event at the first-harm turn, else censored at the conversation length."""
    times, events = [], []
    for t in trials:
        if t["status"] not in ("complete", "harm") or t["arm"] != "adversarial":
            continue
        if t["first_harm_turn"]:
            times.append(t["first_harm_turn"])
            events.append(True)
        else:
            times.append(t["n_turns"] or max_turns)
            events.append(False)
    return times, events


def _arm_entry(store, run: dict) -> dict:
    from .runner import trial_metrics_rows  # local import avoids a cycle
    trials = store.trials_for_run(run["id"])
    summ = metrics.summarize(trial_metrics_rows(trials))
    adv = summ["adversarial"]
    times, events = _survival(trials, (run.get("config") or {}).get("max_turns", 8))
    return {
        "run_id": run["id"],
        "arm": (run.get("config") or {}).get("ablation_arm", "?"),
        "target_label": target_label(run),
        "trials": adv["trials"],
        "trials_with_harm": adv["trials_with_harm"],
        "attack_success": adv["conversation_risk"],
        "response_risk": adv["response_risk"],
        "median_prompts_to_harm": adv["prompts_until_harm"]["km"].get("median"),
        "_times": times, "_events": events,
    }


def analyze(store, run_ids: list[str]) -> dict:
    """Per-arm metrics + each component's marginal effect vs the reference arm."""
    entries: dict[str, dict] = {}
    for rid in run_ids:
        run = store.get_run(rid)
        if not run or run.get("status") != "complete":
            continue
        e = _arm_entry(store, run)
        entries[e["arm"]] = e  # one run per arm in a matched set

    ref = entries.get(REFERENCE_KEY)
    arms_out = []
    for arm in ARMS:
        e = entries.get(arm["key"])
        if not e:
            continue
        row = {"key": arm["key"], "label": arm["label"], "kind": arm["kind"],
               "desc": arm["desc"], "run_id": e["run_id"], "trials": e["trials"],
               "attack_success": e["attack_success"], "response_risk": e["response_risk"],
               "median_prompts_to_harm": e["median_prompts_to_harm"],
               "delta_vs_full": None, "logrank": None}
        if ref and arm["key"] != REFERENCE_KEY and e["trials"] and ref["trials"]:
            # component contribution = reference success − ablated success
            row["delta_vs_full"] = metrics.risk_difference(
                ref["trials_with_harm"], ref["trials"], e["trials_with_harm"], e["trials"])
            row["logrank"] = metrics.log_rank(ref["_times"], ref["_events"], e["_times"], e["_events"])
        arms_out.append(row)

    target = ref["target_label"] if ref else (next(iter(entries.values()))["target_label"] if entries else "?")
    return {"n_arms": len(arms_out), "target_label": target,
            "has_reference": ref is not None, "arms": arms_out}


# -- rendering ----------------------------------------------------------------

def _delta_cell(rd: dict | None) -> str:
    if not rd or rd.get("value") is None:
        return '<td class="n muted">—</td>'
    v, lo, hi = rd["value"], rd.get("lo"), rd.get("hi")
    sig = lo is not None and hi is not None and (lo > 0 or hi < 0)
    pp = f"{v * 100:+.1f} pp"
    ci = f"<br><span class='small muted'>{lo * 100:+.1f} to {hi * 100:+.1f}</span>" if lo is not None else ""
    weight = "font-weight:600" if sig else ""
    return f'<td class="n" style="{weight}">{pp}{ci}</td>'


def render_html(an: dict) -> str:
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for a in an["arms"]:
        tag = {"reference": "reference", "baseline": "baseline"}.get(a["kind"], "ablation")
        p = a["logrank"]["p"] if a.get("logrank") else None
        p_txt = "—" if p is None else (f"{p:.3f}" if p >= 0.001 else "&lt;0.001")
        rows.append(
            f"<tr><td><b>{escape(a['label'])}</b> <span class='muted small'>{tag}</span>"
            f"<br><a class='small' href='/runs/{escape(a['run_id'])}'>run</a>"
            f"<br><span class='muted small'>{escape(a['desc'])}</span></td>"
            f"<td class='n'>{a['trials']}</td>"
            f"<td class='n'>{report._ci(a['attack_success'])}</td>"
            f"<td class='n'>{'not reached' if a['median_prompts_to_harm'] is None else a['median_prompts_to_harm']}</td>"
            + _delta_cell(a.get("delta_vs_full"))
            + f"<td class='n'>{p_txt}</td></tr>")
    body = "".join(rows) or ('<tr><td colspan="6" class="muted" style="text-align:center;padding:24px">'
                             'No completed arms yet.</td></tr>')
    note = ("" if an["has_reference"] else
            '<div class="warn">No reference (full-stack) arm found in this set — Δ columns are blank. '
            'Include the <code>full</code> arm to get component contrasts.</div>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ablation &amp; baselines — sauce.ai/redteam</title>
<style>{report.CSS}</style></head><body>{report.NAV}<div class="wrap">
<h1>Ablation &amp; baselines</h1>
<div class="muted small">sauce.ai/redteam &middot; target <b>{escape(an['target_label'])}</b> &middot;
{an['n_arms']} arms &middot; {when} &middot; adversarial arm &middot; matched personas</div>
<div class="warn">Each arm toggles one orchestrator component on the <em>same</em> persona case-mix (shared seed).
Δ vs full = reference attack success − this arm's (Newcombe 95% CI); positive means the component helps the
attack. Bold Δ excludes 0. The log-rank p tests time-to-harm vs the full stack. Descriptive, LLM-judge based;
the confirmatory paired model belongs in the analysis repo.</div>
{note}
<table><tr><th>Arm</th><th>Conversations</th><th>Attack success (95% CI)</th>
<th>Median prompts&nbsp;to&nbsp;harm</th><th>&Delta; vs full (pp)</th><th>log-rank p</th></tr>{body}</table>
<p class="small muted">Arms: full stack (reference), one ablation per component (bandit, ensemble, refinement,
lookahead, consensus), and a single-prompt baseline. For the design see RESEARCH.md §7 and the pre-registration.</p>
</div></body></html>"""
