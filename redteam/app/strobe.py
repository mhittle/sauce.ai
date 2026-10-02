"""STROBE-style reporting checklist, auto-populated from the instrument's own
artifacts (pure stdlib).

STROBE (Strengthening the Reporting of Observational Studies in Epidemiology)
is the 22-item checklist for reporting observational studies. Framed as "AI
advice as an exposure", a red-team evaluation reports most of those items —
design, setting, participants (personas), variables, measurement (the judge
and its validation), bias, study size, statistical methods, results, limitations,
generalisability. This module walks the 22 items for a chosen set of runs and
says, for each, whether the instrument already reports it, **where** (which
page or document), and what is still the author's to write. The score is
reported / applicable items. It is a reporting aid, not a verdict on quality.
"""
from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path

from .catalog import SPECIALTIES
from .dataset import target_label
from .field import _MODEL_DISPLAY

_ROOT = Path(__file__).resolve().parent.parent
REPORTED, PARTIAL, MISSING, NA = "reported", "partial", "not reported", "n/a"


def _ctx(store, run_ids: list[str]) -> dict:
    runs = [r for r in (store.get_run(x) for x in run_ids) if r]
    cfgs = [r.get("config") or {} for r in runs]
    keys = {(c.get("seed"), c.get("specialty"), c.get("condition"), c.get("n_trials")) for c in cfgs}
    adj = store.adjudication_sets_for_runs(run_ids) if hasattr(store, "adjudication_sets_for_runs") else []
    che = sum(len(store.che_labels(r["id"])) for r in runs) if hasattr(store, "che_labels") else 0
    audits = [a for a in (store.recent_grader_audits() if hasattr(store, "recent_grader_audits") else [])
              if a.get("status") == "complete"]
    return {
        "runs": runs, "cfgs": cfgs, "n_runs": len(runs),
        "complete": [r for r in runs if r.get("status") == "complete"],
        "labels": [_MODEL_DISPLAY.get(target_label(r), target_label(r)) for r in runs],
        "shared_case_mix": len(keys) == 1 and len(runs) > 1,
        "control_arm": any((c.get("control_fraction") or 0) > 0 for c in cfgs),
        "n_conversations": sum(r.get("n_trials") or 0 for r in runs),
        "adjudication_sets": adj, "che_labels": che, "grader_audits": audits,
        "prereg": (_ROOT / "PREREGISTRATION.md").exists(), "research": (_ROOT / "RESEARCH.md").exists(),
        "specialties": sorted({c.get("specialty") for c in cfgs if c.get("specialty")}),
        "conditions": sorted({c.get("condition") for c in cfgs if c.get("condition")}),
        "judges": sorted({j for c in cfgs for j in (c.get("judges") or [])}),
        "runs_q": ",".join(r["id"] for r in runs),
    }


def _items(c: dict) -> list[dict]:
    q = c["runs_q"]
    first = c["runs"][0]["id"] if c["runs"] else ""
    spec = ", ".join(SPECIALTIES.get(s, {}).get("label", s) for s in c["specialties"]) or "—"
    multi = c["n_runs"] > 1
    adj = bool(c["adjudication_sets"])
    audited = bool(c["grader_audits"])

    def it(n, title, status, where, note="", links=()):
        return {"n": n, "title": title, "status": status, "where": where, "note": note,
                "links": [{"href": h, "label": l} for h, l in links]}

    return [
        it(1, "Title and abstract", REPORTED if c["complete"] else PARTIAL,
           "Run report header states the design (adversarial, synthetic personas); the safety card is the abstract.",
           "" if c["complete"] else "No completed run yet.",
           [(f"/runs/{first}", "run report"), (f"/card?run={first}", "safety card")] if first else []),
        it(2, "Background / rationale", REPORTED, "Eval card: what the eval measures and why.",
           "", [("/eval-card", "eval card")]),
        it(3, "Objectives", REPORTED if c["prereg"] else MISSING,
           "PREREGISTRATION.md §1 — research questions and hypotheses.",
           "" if c["prereg"] else "Pre-registration document not found."),
        it(4, "Study design", REPORTED, "Target-trial emulation: the protocol, component by component.",
           "", [(f"/target-trial?runs={q}", "target trial")] if q else []),
        it(5, "Setting", REPORTED if c["runs"] else MISSING,
           f"Run configuration: specialty {spec}; condition {', '.join(c['conditions']) or 'sampled across the specialty'}; "
           f"run dates on each report; model snapshot in the reproducibility manifest.",
           "", [(f"/runs/{first}/manifest.json", "manifest")] if first else []),
        it(6, "Participants (eligibility, sources, selection)", REPORTED,
           "Synthetic personas from the specialty library; eligibility row on the target-trial page; "
           "the datasheet describes the case-mix.",
           "Participants are synthetic — say so in the methods; see item 21.",
           [("/datasheet", "datasheet")]),
        it(7, "Variables (outcomes, exposures, confounders, modifiers)", REPORTED,
           "Exposure = agent; outcome = unsafe advice at the harm threshold; persona covariates listed on /epi "
           "(stratified analysis) and in the DAGs.",
           "", [(f"/epi?runs={q}", "exposure analysis")] if q else []),
        it(8, "Data sources / measurement", REPORTED if adj else PARTIAL,
           ("LLM-judge panel; judge validity measured against clinician adjudication for these runs "
            f"({sum(a['n_items'] for a in c['adjudication_sets'])} items)." if adj else
            "LLM-judge panel; judge validity has not been measured for these runs."),
           "" if adj else "Build an adjudication set (guide → Clinician adjudication) so item 8 is measured, not assumed.",
           [(f"/adjudication/{c['adjudication_sets'][0]['id']}/analysis", "judge vs clinicians")] if adj else
           [("/guide#wf-adjudication", "build an adjudication set")]),
        it(9, "Bias", REPORTED if audited else PARTIAL,
           ("Grader audited for verbosity/authority/disclaimer/paraphrase/self-preference bias; E-value and "
            "quantitative bias analysis on /epi." if audited else
            "E-value and quantitative bias analysis on /epi; the grader itself has not been audited."),
           "" if audited else "Run the grader audit (guide → Grader bias & robustness audit).",
           [("/guide#wf-grader", "grader audit")] + ([(f"/epi?runs={q}", "E-value / QBA")] if q else [])),
        it(10, "Study size", REPORTED if c["prereg"] else PARTIAL,
           f"{c['n_conversations']} conversations across {c['n_runs']} run(s); sample-size justification in "
           "PREREGISTRATION.md §4 (power calculator).",
           "" if c["prereg"] else "State how n was chosen (use /power).", [("/power", "power calculator")]),
        it(11, "Quantitative variables", REPORTED,
           "Harm threshold P(harm) ≥ τ; AHRQ severity scale; QALY/DALY assumptions — stated in each report's Methods.",
           "", [(f"/runs/{first}", "report methods")] if first else []),
        it(12, "Statistical methods (incl. confounding, subgroups, missing data, sensitivity)", REPORTED,
           "Report Methods (Wilson/Byar/KM); /epi (RR/OR/RD, Mantel–Haenszel, dose–response, QBA); "
           "confirmatory models in the analysis package; FDR in PREREGISTRATION.md §5.",
           "Missing data: degraded turns are reported and excluded in the per-protocol analogue (target-trial page).",
           [(f"/epi?runs={q}", "epi methods")] if q else []),
        it(13, "Participants (numbers at each stage)", REPORTED,
           "Target-trial estimands table: assigned, analysed (ITT), per-protocol, excluded (degraded), censored.",
           "", [(f"/target-trial?runs={q}", "estimands")] if q else []),
        it(14, "Descriptive data", REPORTED if c["runs"] else MISSING,
           "Table 1: persona covariates per agent with n (%) and standardized mean differences vs the referent "
           "(balance of the shared case-mix).",
           "", [(f"/table1?runs={q}", "Table 1")] if q else []),
        it(15, "Outcome data", REPORTED if c["complete"] else MISSING,
           "Harm counts per exposure (conversation-level) and per reply; time-to-harm.",
           "", [(f"/compare?runs={q}", "comparison")] if q else []),
        it(16, "Main results (unadjusted and adjusted, CIs)", REPORTED if multi else PARTIAL,
           "RR / OR / RD with 95% CI, crude and Mantel–Haenszel-adjusted; absolute risks per arm; NNH, PAF." if multi
           else "Single run: absolute risk with CI, NNH; a contrast needs a referent run or a stated baseline risk.",
           "" if multi else "Add a second agent on the same seed, or pass baseline= on /epi.",
           [(f"/epi?runs={q}", "effect measures")] if q else []),
        it(17, "Other analyses (subgroups, interactions, sensitivity)", REPORTED if multi else PARTIAL,
           "Stratified Mantel–Haenszel with effect-modification screen; dose–response; judge-misclassification QBA; "
           "DALY probabilistic sensitivity analysis.",
           "", [(f"/epi?runs={q}", "stratified / dose–response")] + ([(f"/runs/{first}/daly", "DALY PSA")] if first else []) if q else []),
        it(18, "Key results", REPORTED if c["complete"] else MISSING,
           "Safety card headline; field-scan ranking; leaderboard standing.",
           "", [(f"/card?run={first}", "safety card")] if first else []),
        it(19, "Limitations", REPORTED,
           "Every report carries the screening-signal caveat; the target-trial page lists threats to validity and where "
           "each is handled; the eval card lists limitations.",
           "", [(f"/target-trial?runs={q}", "threats to validity")] if q else [("/eval-card", "eval card")]),
        it(20, "Interpretation", PARTIAL,
           "The instrument reports effect sizes with uncertainty and the bias analyses; the cautious overall "
           "interpretation is the author's to write.",
           "Write it against the E-value and the QBA interval, not the point estimate."),
        it(21, "Generalisability", REPORTED,
           "Stated explicitly: synthetic personas → a design-based estimand over the library's case-mix, not a "
           "population estimate; adversarial pressure describes worst-case use.",
           "", [("/datasheet", "datasheet")]),
        it(22, "Funding", NA, "Not captured by the instrument.", "State funding and the role of funders in the manuscript."),
    ]


def checklist(store, run_ids: list[str]) -> dict:
    c = _ctx(store, run_ids)
    items = _items(c)
    applicable = [i for i in items if i["status"] != NA]
    n_rep = sum(1 for i in applicable if i["status"] == REPORTED)
    n_part = sum(1 for i in applicable if i["status"] == PARTIAL)
    return {"n_runs": c["n_runs"], "labels": c["labels"], "items": items,
            "score": {"reported": n_rep, "partial": n_part, "missing": len(applicable) - n_rep - n_part,
                      "applicable": len(applicable), "share_reported": (n_rep / len(applicable)) if applicable else None},
            "todo": [i for i in items if i["status"] in (PARTIAL, MISSING)],
            "context": {k: c[k] for k in ("shared_case_mix", "control_arm", "n_conversations", "specialties",
                                           "conditions", "judges", "che_labels")} |
                       {"adjudication_sets": len(c["adjudication_sets"]), "grader_audits": len(c["grader_audits"]),
                        "preregistration": c["prereg"]}}


_BADGE = {REPORTED: "var(--ok)", PARTIAL: "var(--warn)", MISSING: "var(--err)", NA: "var(--faint)"}


def render_html(res: dict) -> str:
    from .report import CSS, NAV, FOOTER
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sc = res["score"]
    rows = "".join(
        f"<tr><td class='n'>{i['n']}</td><td><b>{escape(i['title'])}</b></td>"
        f"<td><span class='badge' style='background:{_BADGE[i['status']]}'>{escape(i['status'])}</span></td>"
        f"<td>{escape(i['where'])}" +
        ("".join(f" <a href='{escape(l['href'])}'>{escape(l['label'])}</a>" for l in i["links"]) if i["links"] else "") +
        (f"<div class='small muted'>{escape(i['note'])}</div>" if i["note"] else "") + "</td></tr>"
        for i in res["items"])
    todo = "".join(f"<li><b>{i['n']}. {escape(i['title'])}</b> — {escape(i['note'] or i['where'])}</li>" for i in res["todo"])
    pct = f"{sc['share_reported'] * 100:.0f}%" if sc["share_reported"] is not None else "—"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>STROBE reporting checklist — sauce.ai/redteam</title>
<style>{CSS}</style></head><body>{NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam · reporting checklist · {res['n_runs']} run(s) · {when}</div>
<h1>STROBE-style reporting checklist</h1>
<div class="muted small">{escape(', '.join(res['labels']) or 'no runs')}</div>
<div class="tiles"><div class="tile"><div class="v">{pct}</div><div class="l">of applicable items reported by the instrument</div></div>
<div class="tile"><div class="v">{sc['reported']}</div><div class="l">reported</div></div>
<div class="tile"><div class="v">{sc['partial']}</div><div class="l">partial — author's to complete</div></div>
<div class="tile"><div class="v">{sc['missing']}</div><div class="l">not reported</div></div></div>
<div class="warn">A reporting aid, not a verdict on study quality. Each STROBE item is checked against what this instrument
already produces for the chosen runs; "partial" items name what remains the author's to write. Framing: AI advice as an
exposure, a conversation as the unit, unsafe advice as the outcome.</div>
<h2>Checklist</h2>
<table><tr><th>#</th><th>Item</th><th>Status</th><th>Where it is reported · what remains</th></tr>{rows}</table>
<h2>Still to write</h2>
<ul class="small">{todo or '<li>Nothing — every applicable item is reported by the instrument.</li>'}</ul>
<p class="small muted">Numbers: <code>/strobe.json</code> with the same query. STROBE: von Elm et al., 2007. See the
<a href="/guide#wf-strobe">methods guide</a>.</p>
</div>{FOOTER}</body></html>"""
