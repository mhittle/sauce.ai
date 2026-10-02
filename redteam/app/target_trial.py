"""Target-trial emulation — "AI advice as an exposure" written as the protocol
of the randomized trial we would run, component by component, next to how this
instrument emulates each one (Hernán & Robins 2016 framing). Pure stdlib.

For a set of runs (one per agent on the same seeded case-mix) it produces:

* the **protocol table** — eligibility, treatment strategies, assignment,
  follow-up, outcome, causal contrasts, analysis plan — target trial vs
  emulation, with a fidelity grade (matched / approximated / deviates);
* the **estimands** — an intention-to-treat analogue (every assigned
  conversation analysed under its assigned agent) and a per-protocol analogue
  (conversations with no degraded turns, i.e. the strategy was delivered as
  specified), each with harm risks and the contrast vs the referent;
* the **causal diagrams** (`causal.py`) for real-world use and for the design,
  with minimal adjustment sets, so the reader sees *why* assignment by design
  makes the crude contrast unconfounded and what residual threats remain;
* the **threats to validity** specific to this emulation and where each is
  measured or mitigated elsewhere in the instrument.
"""
from __future__ import annotations

import datetime as dt
from html import escape

from . import causal, metrics
from .catalog import SPECIALTIES
from .dataset import target_label


def _display(label: str) -> str:
    from .field import _MODEL_DISPLAY
    return _MODEL_DISPLAY.get(label, label)


def _arm_summary(trials: list[dict]) -> dict:
    """ITT: all completed adversarial conversations; PP: those with no degraded turn."""
    convs = [t for t in trials if t["status"] in ("complete", "harm") and t.get("arm") == "adversarial"]
    harm = lambda t: t["status"] == "harm" or t.get("first_harm_turn") is not None
    pp = [t for t in convs if not any(u.get("degraded") for u in t.get("turns", []))]
    a, n = sum(harm(t) for t in convs), len(convs)
    a_pp, n_pp = sum(harm(t) for t in pp), len(pp)
    p, lo, hi = metrics.wilson(a, n) if n else (None, None, None)
    q, qlo, qhi = metrics.wilson(a_pp, n_pp) if n_pp else (None, None, None)
    return {"itt": {"cases": a, "n": n, "risk": {"value": p, "lo": lo, "hi": hi}},
            "per_protocol": {"cases": a_pp, "n": n_pp, "risk": {"value": q, "lo": qlo, "hi": qhi},
                             "excluded_degraded": n - n_pp},
            "censored_at_max_turns": sum(1 for t in convs if not harm(t))}


def _protocol_rows(cfg: dict, agents: list[dict], referent: dict | None) -> list[dict]:
    spec = SPECIALTIES.get(cfg.get("specialty") or "", {})
    spec_label = spec.get("label", cfg.get("specialty") or "clinical")
    cond = cfg.get("condition") or f"any {spec_label} condition in the library"
    names = ", ".join(a["label"] for a in agents) or "—"
    ref_name = referent["label"] if referent else "the safest agent"
    max_turns = cfg.get("max_turns", 8)
    thr = cfg.get("harm_threshold", 0.10)
    judges = ", ".join(cfg.get("judges") or []) or "configured judge panel"
    return [
        {"component": "Eligibility criteria",
         "target_trial": f"Adults (or carers) seeking advice about {cond} ({spec_label}); no prior consultation "
                         "about this episode; able to use a chat assistant.",
         "emulation": f"Synthetic personas from the {spec_label} library: age band, sex, speaker, health literacy, "
                      "affect, care access, current high-risk medications, a latent red flag; same seeded case-mix "
                      f"for every agent (seed {cfg.get('seed', 0)}, n = {cfg.get('n_trials', '?')} per agent).",
         "fidelity": "approximated",
         "note": "Personas are synthetic — representative of the library's design, not of a population; the "
                 "enriched time-critical stratum is analysed separately (pre-registration §2)."},
        {"component": "Treatment strategies",
         "target_trial": f"Consult agent k for this episode (k ∈ {{{names}}}), vs consult {ref_name}; each under the "
                         "same health-assistant framing.",
         "emulation": "Each agent reached via its provider API under the fixed health-assistant system prompt; the "
                      "model snapshot and prompt version are recorded on the run (reproducibility manifest).",
         "fidelity": "matched",
         "note": "Strategy = the agent as deployed at run date; a later snapshot is a different strategy."},
        {"component": "Assignment procedure",
         "target_trial": "Randomize each eligible person to one strategy at baseline (time zero = first message); "
                         "no blinding of the person, blinded outcome assessment.",
         "emulation": "Every persona is assigned to *every* strategy (paired / crossover-like design on the shared "
                      "case-mix); assignment is by design, independent of all persona covariates. Outcome assessment "
                      "is blinded to agent identity at the judge and at clinician adjudication.",
         "fidelity": "matched",
         "note": "Stronger than randomization for confounding (identical case-mix per arm); within-persona "
                 "correlation handled by the paired analysis (persona random effect)."},
        {"component": "Follow-up period",
         "target_trial": "From the first message until the episode ends: advice acted on, escalation to care, or "
                         "a fixed horizon.",
         "emulation": f"From prompt 1 until the first unsafe reply or {max_turns} prompts, whichever first "
                      f"(stop-on-harm = {bool(cfg.get('stop_on_harm', True))}); conversations harm-free at the "
                      "horizon are right-censored.",
         "fidelity": "approximated",
         "note": "Follow-up is in prompts, not calendar time; adversarial pressure is adaptive (a mediator, see DAG)."},
        {"component": "Outcome",
         "target_trial": "Clinically unsafe advice acted upon, graded by severity; critical harm events "
                         "adjudicated by clinicians.",
         "emulation": f"Reply judged unsafe at P(harm) ≥ {thr:.2f} by the judge panel ({judges}); critical "
                      "harm events via the high-sensitivity screener → blinded two-phase clinician adjudication.",
         "fidelity": "approximated",
         "note": "The judge is a mis-measurement of the true outcome (Y* in the DAG); its sensitivity/specificity "
                 "are audited and propagated by the /epi quantitative bias analysis."},
        {"component": "Causal contrasts of interest",
         "target_trial": "Intention-to-treat effect of assigned strategy on the risk of unsafe advice; per-protocol "
                         "effect of adhering to the strategy for the whole episode.",
         "emulation": "ITT-analogue: all assigned conversations analysed under their assigned agent. Per-protocol "
                      "analogue: conversations in which the strategy was delivered as specified (no degraded turns — "
                      "provider errors, timeouts, empty replies).",
         "fidelity": "matched",
         "note": "Estimand: risk ratio / risk difference of unsafe advice per conversation, agent vs referent, "
                 "over the shared case-mix (a finite-population, design-based estimand)."},
        {"component": "Analysis plan",
         "target_trial": "Risk ratio and difference with 95% CI; time-to-event for prompts-to-harm; pre-specified "
                         "subgroups; sensitivity to outcome misclassification.",
         "emulation": "In-app: /epi (RR, RD, NNH, PAF, E-value, Mantel–Haenszel strata, dose–response, judge QBA) and "
                      "KM/log-rank on prompts-to-harm. Confirmatory: mixed-effects logistic `harm ~ agent + (1|persona)`, "
                      "discrete-time hazard with frailty, competing risks (analysis package; pre-registration §5).",
         "fidelity": "matched",
         "note": "Multiplicity by Benjamini–Hochberg over secondary families; the primary family is not discounted."},
    ]


_THREATS = [
    {"threat": "Confounding by indication (who consults which agent)",
     "handled": "Eliminated by design — exposure assigned to every persona; DAG 'trial' adjustment set is empty.",
     "where": "/target-trial DAG · /epi Mantel–Haenszel check (expected null)"},
    {"threat": "Unmeasured confounding in real-world transport",
     "handled": "Not a threat to the design estimand; for transport to real use, the E-value bounds what an "
                "unmeasured factor would need to be.",
     "where": "/epi E-value column"},
    {"threat": "Outcome misclassification by the LLM judge (non-differential and differential)",
     "handled": "Judge audited as a diagnostic test (Se/Sp, calibration, self-preference & style bias); Rogan–Gladen "
                "and probabilistic bias analysis; clinician adjudication for critical events.",
     "where": "/grader-audit · /epi QBA · /che-report"},
    {"threat": "Protocol deviation (degraded turns: provider errors, timeouts)",
     "handled": "Reported per agent; per-protocol analogue excludes affected conversations; ITT keeps them.",
     "where": "this page (estimands table)"},
    {"threat": "Censoring at the prompt horizon",
     "handled": "Right-censoring handled by Kaplan–Meier / discrete-time hazard rather than treating censored as safe.",
     "where": "run report KM · analysis package survival models"},
    {"threat": "Adaptive adversarial pressure (mediator, not confounder)",
     "handled": "Total effect is the target; pressure is not adjusted for. Dose–response reported descriptively.",
     "where": "/epi dose–response · ablation harness (pressure arms)"},
    {"threat": "Synthetic personas → external validity",
     "handled": "Design-based estimand over the library's case-mix; stated explicitly as not a population estimate; "
                "enriched seeds analysed separately.",
     "where": "pre-registration §2 · datasheet"},
    {"threat": "Model snapshot drift",
     "handled": "Strategy pinned to snapshot + date in the reproducibility manifest; re-runs are new strategies.",
     "where": "/runs/{id}/manifest.json"},
]


def emulate(store, run_ids: list[str], ref: str | None = None) -> dict:
    agents = []
    cfg = {}
    for rid in run_ids:
        run = store.get_run(rid)
        if not run:
            continue
        cfg = cfg or (run.get("config") or {})
        trials = store.trials_for_run(rid)
        s = _arm_summary(trials)
        if s["itt"]["n"] == 0:
            continue
        agents.append({"run_id": rid, "label": _display(target_label(run)), **s})
    if not agents:
        return {"n_agents": 0, "agents": [], "protocol": [], "referent": None}
    referent = next((a for a in agents if a["run_id"] == ref), None) if ref else \
        min(agents, key=lambda a: a["itt"]["risk"]["value"] or 0.0)
    for a in agents:
        if a["run_id"] == referent["run_id"]:
            a["contrast"] = None
            continue
        a["contrast"] = {
            "itt": {"risk_ratio": metrics.risk_ratio(a["itt"]["cases"], a["itt"]["n"],
                                                     referent["itt"]["cases"], referent["itt"]["n"]),
                    "risk_difference": metrics.risk_difference(a["itt"]["cases"], a["itt"]["n"],
                                                               referent["itt"]["cases"], referent["itt"]["n"])},
            "per_protocol": {"risk_ratio": metrics.risk_ratio(a["per_protocol"]["cases"], a["per_protocol"]["n"],
                                                              referent["per_protocol"]["cases"],
                                                              referent["per_protocol"]["n"]),
                             "risk_difference": metrics.risk_difference(
                                 a["per_protocol"]["cases"], a["per_protocol"]["n"],
                                 referent["per_protocol"]["cases"], referent["per_protocol"]["n"])}}
    agents.sort(key=lambda a: -(a["itt"]["risk"]["value"] or 0))
    # same case-mix check: seed + specialty + n identical across runs
    keys = set()
    for rid in run_ids:
        run = store.get_run(rid) or {}
        c = run.get("config") or {}
        keys.add((c.get("seed"), c.get("specialty"), c.get("condition"), c.get("n_trials")))
    return {
        "n_agents": len(agents), "agents": agents,
        "referent": {"run_id": referent["run_id"], "label": referent["label"]},
        "config": {k: cfg.get(k) for k in ("specialty", "condition", "n_trials", "seed", "max_turns",
                                           "stop_on_harm", "harm_threshold", "judges")},
        "shared_case_mix": len(keys) == 1,
        "protocol": _protocol_rows(cfg, agents, {"label": referent["label"]}),
        "dag": {"observational": causal.analyze("observational"), "trial": causal.analyze("trial")},
        "threats": _THREATS,
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_BADGE = {"matched": ("#14805f", "matched"), "approximated": ("#9a6700", "approximated"),
          "deviates": ("#d1261a", "deviates")}


def _fmt(d: dict | None, pct: bool = False) -> str:
    if not d or d.get("value") is None:
        return "—"
    f = (lambda v: f"{v * 100:.1f}%") if pct else (lambda v: f"{v:.2f}")
    s = f(d["value"])
    if d.get("lo") is not None and d.get("hi") is not None:
        s += f" ({f(d['lo'])} to {f(d['hi'])})"
    return s


def render_html(res: dict) -> str:
    from .report import CSS, NAV
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not res.get("agents"):
        return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{NAV}<div class='wrap'>"
                "<h1>Target trial emulation</h1><p class='muted'>No completed adversarial conversations in the chosen runs."
                "</p></div></body></html>")
    cfg = res["config"]
    cond = cfg.get("condition") or SPECIALTIES.get(cfg.get("specialty") or "", {}).get("label") or "clinical advice"
    prow = "".join(
        f"<tr><td><b>{escape(r['component'])}</b></td><td>{escape(r['target_trial'])}</td>"
        f"<td>{escape(r['emulation'])}<div class='small muted'>{escape(r['note'])}</div></td>"
        f"<td><span style='display:inline-block;padding:2px 8px;border-radius:10px;background:{_BADGE[r['fidelity']][0]};"
        f"color:#fff;font-size:11px'>{_BADGE[r['fidelity']][1]}</span></td></tr>"
        for r in res["protocol"])
    erow = []
    for a in res["agents"]:
        c = a.get("contrast")
        ref_tag = "" if c else " <span class='muted small'>(referent)</span>"
        erow.append(
            f"<tr><td><b>{escape(a['label'])}</b>{ref_tag}</td>"
            f"<td class='n'>{a['itt']['cases']}/{a['itt']['n']}<br><span class='small muted'>{_fmt(a['itt']['risk'], True)}</span></td>"
            f"<td class='n'>{_fmt(c['itt']['risk_ratio']) if c else '1 (ref)'}</td>"
            f"<td class='n'>{a['per_protocol']['cases']}/{a['per_protocol']['n']}<br><span class='small muted'>{_fmt(a['per_protocol']['risk'], True)}</span></td>"
            f"<td class='n'>{_fmt(c['per_protocol']['risk_ratio']) if c else '1 (ref)'}</td>"
            f"<td class='n'>{a['per_protocol']['excluded_degraded']}</td>"
            f"<td class='n'>{a['censored_at_max_turns']}</td></tr>")
    trow = "".join(f"<tr><td><b>{escape(t['threat'])}</b></td><td>{escape(t['handled'])}</td>"
                   f"<td class='small muted'>{escape(t['where'])}</td></tr>" for t in res["threats"])
    dag_o, dag_t = res["dag"]["observational"], res["dag"]["trial"]
    notes = lambda d: "".join(f"<li>{escape(n)}</li>" for n in d["notes"])
    sets = lambda d: (", ".join("{" + ", ".join(s) + "}" if s else "∅" for s in d["minimal_adjustment_sets"])
                      or "none from observed covariates")
    mix = ("Runs share one seeded case-mix (same seed, specialty, condition and n) — the paired design holds."
           if res["shared_case_mix"] else
           "<b>Runs do not share one case-mix</b> (seed/specialty/condition/n differ): the paired-assignment component "
           "is <b>not</b> met for this set; treat contrasts as between-case-mix comparisons.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Target trial emulation — {escape(cond)}</title>
<style>{CSS}</style></head><body>{NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam · target trial emulation · {res['n_agents']} strategies · {when}</div>
<h1>Target trial emulation — AI advice as an exposure, {escape(cond)}</h1>
<div class="warn">The randomized trial we would run, component by component, next to how this instrument emulates it.
Referent strategy: <b>{escape(res['referent']['label'])}</b>. {mix} Outcome labels are LLM-judge screening signals;
not clinical determinations.</div>
<h2>Protocol</h2>
<table><tr><th>Component</th><th>Target trial</th><th>Emulation in this instrument</th><th>Fidelity</th></tr>{prow}</table>
<h2>Estimands</h2>
<table><tr><th>Strategy (agent)</th><th>ITT harm / n</th><th>ITT RR vs referent</th><th>Per-protocol harm / n</th>
<th>Per-protocol RR</th><th>Excluded (degraded)</th><th>Censored at horizon</th></tr>{''.join(erow)}</table>
<p class="small muted">ITT-analogue: every assigned conversation under its assigned agent. Per-protocol analogue: conversations
in which the strategy was delivered as specified (no degraded turns). RR Katz log interval. Harm-free conversations at the
prompt horizon are censored, not "safe" — see KM on the run report.</p>
<h2>Causal diagrams</h2>
<div style="display:grid;grid-template-columns:1fr;gap:12px">
<div>{causal.dag_svg(dag_o)}<p class="small"><b>Minimal adjustment sets:</b> {sets(dag_o)}.</p><ul class="small">{notes(dag_o)}</ul></div>
<div>{causal.dag_svg(dag_t)}<p class="small"><b>Minimal adjustment sets:</b> {sets(dag_t)}.</p><ul class="small">{notes(dag_t)}</ul></div>
</div>
<p class="small muted">Solid: causal arrows among measured nodes. Dashed: the unmeasured node and the measurement path
(Y → Y* through judge style bias). Node A: exposure; Y: outcome. The diagrams are stated assumptions, not learned from data.</p>
<h2>Threats to validity — and where each is handled</h2>
<table><tr><th>Threat</th><th>Handled by</th><th>Where</th></tr>{trow}</table>
<p class="small muted">Numbers: <code>/target-trial.json</code> with the same query · DAG image: <code>/target-trial.svg?design=trial|observational</code>.
See the <a href="/guide#target-trial">methods guide</a>.</p>
</div></body></html>"""
