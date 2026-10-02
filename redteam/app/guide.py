"""Methods & workflows guide — a single page mapping every capability we've
built, with how-to-run instructions.

The workflow catalogue below is the single source of truth: the page is rendered
from it, and a test checks every HTTP path it references is a real route, so the
guide can't drift from the service.
"""
from __future__ import annotations

from html import escape

# Each workflow: title, summary, when-to-use, and steps. An HTTP step is
# {"m": METHOD, "p": PATH, "note": ...}; a shell step is {"cmd": ..., "note": ...}.
GROUPS: list[dict] = [
    {"stage": "Run an evaluation", "anchor": "run",
     "blurb": "Point the service at a clinical chatbot you're authorized to test; it runs adversarial "
              "synthetic-patient conversations and emails an epidemiological report.",
     "workflows": [
         {"title": "Submit a red-team run", "id": "submit",
          "summary": "The core workflow. Choose a target endpoint, a specialty, and a number of trials; "
                     "the orchestrator drives conversations toward unsafe advice and a judge panel scores "
                     "every reply. Free while in preview (100 trials per email).",
          "when": "You own or have written permission to test the target.",
          "steps": [
              {"m": "POST", "p": "/runs",
               "note": "body: email, target{kind,url,model,api_key,…}, specialty, n_trials, "
                       "optional condition/focus_harms/max_turns/control_fraction/harm_threshold/seed/"
                       "orchestration/judges"},
              {"m": "GET", "p": "/runs/{run_id}/status", "note": "poll progress"},
              {"m": "GET", "p": "/runs/{run_id}", "note": "the full HTML report (also emailed)"},
              {"m": "POST", "p": "/runs/{run_id}/cancel", "note": "stop a running job"},
          ]},
     ]},
    {"stage": "Results & sharing", "anchor": "results",
     "blurb": "Turn a completed run into legible, shareable artifacts and compare across models.",
     "workflows": [
         {"title": "Public safety leaderboard", "id": "leaderboard",
          "summary": "Every completed run is auto-ranked here by a severity-weighted safety score, per "
                     "clinical specialty plus an overall view. No extra step.",
          "when": "Always on; browse after any run.",
          "steps": [{"m": "GET", "p": "/leaderboard", "note": "add ?category=<specialty>"},
                    {"m": "GET", "p": "/leaderboard.json", "note": "raw board"}]},
         {"title": "Model safety card + share image", "id": "card",
          "summary": "A per-target card: safety score, rank, attack success, critical failures, a "
                     "time-to-harm curve, top harm categories, and provenance — with Open Graph tags and "
                     "a 1200×630 share image.",
          "when": "Sharing or summarizing a single target's results.",
          "steps": [{"m": "GET", "p": "/card", "note": "?run=<run_id>"},
                    {"m": "GET", "p": "/card/{run_id}/image.svg", "note": "social share image"}]},
         {"title": "Eval card & dataset datasheet", "id": "evalcard",
          "summary": "A model-card for the eval itself (what it measures, elicitation, the audited grader, "
                     "metrics, limitations, standards) and a datasheet-for-datasets for the conversation data.",
          "when": "Documenting the methodology for readers/reviewers.",
          "steps": [{"m": "GET", "p": "/eval-card", "note": "the eval's model card"},
                    {"m": "GET", "p": "/datasheet", "note": "datasheet-for-datasets"}]},
         {"title": "Cross-model comparison", "id": "compare",
          "summary": "A descriptive leaderboard across chosen runs: attack success, harmful-reply risk, "
                     "median prompts-to-harm, NNH, QALYs/1,000, with CIs and overlaid KM curves.",
          "when": "Comparing targets run on the same paired case-mix (same seed+specialty+n).",
          "steps": [{"m": "GET", "p": "/compare", "note": "?runs=<id>,<id>,…"},
                    {"m": "GET", "p": "/compare.json", "note": "raw numbers"}]},
         {"title": "DALY burden (PSA)", "id": "daly",
          "summary": "Expected harm burden as a distribution — DALYs per 1,000 conversations with a 95% "
                     "credible interval from a Monte-Carlo PSA over GBD-informed weights and the harm rate's "
                     "posterior. Illustrative, order-of-magnitude.",
          "when": "Communicating magnitude of harm with its uncertainty.",
          "steps": [{"m": "GET", "p": "/runs/{run_id}/daly", "note": "report + density plot"},
                    {"m": "GET", "p": "/runs/{run_id}/daly.json", "note": "numbers"},
                    {"m": "GET", "p": "/runs/{run_id}/daly.svg", "note": "distribution image"}]},
     ]},
    {"stage": "Validity & methodology", "anchor": "validity",
     "blurb": "Make the measurement trustworthy: audit the grader, validate it against clinicians, and "
              "measure the design-based Critical Harm Rate.",
     "workflows": [
         {"title": "Grader bias & robustness audit", "id": "grader",
          "summary": "Audits the harm judge itself for verbosity / authority / disclaimer laundering, "
                     "paraphrase stability, self-preference (own-family leniency), and calibration "
                     "(Brier/ECE/AUROC). Flags a material shift only when the CI excludes 0 and it clears a "
                     "size floor.",
          "when": "Before trusting any harm numbers; whenever you change the judge model.",
          "steps": [{"m": "POST", "p": "/grader-audit", "note": "body: judges[], threshold"},
                    {"m": "GET", "p": "/grader-audit/{audit_id}", "note": "report"},
                    {"m": "GET", "p": "/grader-audit/{audit_id}.json", "note": "numbers"}]},
         {"title": "Clinician adjudication (judge validation)", "id": "adjudication",
          "summary": "Build a stratified blinded sample, collect independent clinician labels, and score the "
                     "LLM judge as a diagnostic test (κ / AC1, sensitivity/specificity, AUROC, calibration).",
          "when": "Establishing that the judge agrees with clinicians (the validity backbone).",
          "steps": [{"m": "POST", "p": "/adjudication/sets", "note": "body: run_ids[], n, strata…"},
                    {"m": "GET", "p": "/adjudicate/{set_id}", "note": "blinded labeling UI"},
                    {"m": "GET", "p": "/adjudication/{set_id}/analysis", "note": "agreement + diagnostics"},
                    {"m": "GET", "p": "/adjudication/{set_id}/export", "note": "items + labels"}]},
         {"title": "Critical Harm Event (CHE)", "id": "che",
          "summary": "A design-based headline metric: a high-sensitivity screener → two-phase clinician "
                     "review → the Critical Harm Rate (Horvitz–Thompson + exact/bootstrap CIs, rule-of-three), "
                     "with a redacted report.",
          "when": "Reporting the most serious harms with design-based rigor.",
          "steps": [{"m": "POST", "p": "/runs/{run_id}/che/screen", "note": "screen stored replies"},
                    {"m": "POST", "p": "/che/review-sets", "note": "two-phase clinician sample"},
                    {"m": "GET", "p": "/che-review/{set_id}", "note": "blinded clinician UI"},
                    {"m": "GET", "p": "/che/report", "note": "?runs=<id>,… — the CHR report"}]},
     ]},
    {"stage": "Benchmarking & data", "anchor": "data",
     "blurb": "Export analysis-ready data and quantify what the attack orchestrator contributes.",
     "workflows": [
         {"title": "Tidy dataset export", "id": "export",
          "summary": "One analysis-ready row per reply (or per conversation) with every covariate — the input "
                     "to the confirmatory analysis and to Inspect.",
          "when": "Before any off-line statistical modelling.",
          "steps": [{"m": "GET", "p": "/export/tidy.csv", "note": "?runs=<id>,…&level=turn|trial"},
                    {"m": "GET", "p": "/export/tidy.json", "note": "same as JSON"}]},
         {"title": "Ablation & baselines", "id": "ablation",
          "summary": "Launches a matched arm set against one target (full stack, one ablation per component, "
                     "and a single-prompt baseline) sharing the seed, and reports each component's marginal "
                     "effect (Newcombe RD + log-rank).",
          "when": "Showing the orchestrator's components carry their weight (RQ3).",
          "steps": [{"m": "POST", "p": "/ablation", "note": "body: like /runs, plus optional arms[]"},
                    {"m": "GET", "p": "/ablation/{ablation_id}", "note": "contrast report"},
                    {"m": "GET", "p": "/ablation/{ablation_id}.json", "note": "numbers"},
                    {"m": "GET", "p": "/ablation", "note": "ad-hoc: ?runs=<id>,… (pre-tagged runs)"}]},
     ]},
    {"stage": "Planning & reproducibility", "anchor": "planning",
     "blurb": "Size the study before you run it, and make every run reproducible.",
     "workflows": [
         {"title": "Sample-size & power", "id": "power",
          "summary": "A calculator: single-proportion CHR precision, two-proportion n / power / MDE, a "
                     "clustering design effect, the two-phase clinician review burden, and rule-of-three "
                     "zero-event planning.",
          "when": "Planning the confirmatory run.",
          "steps": [{"m": "GET", "p": "/power", "note": "the calculator UI"},
                    {"m": "GET", "p": "/power.json", "note": "mode=precision|two_proportions|mde|review_burden|rule_of_three"}]},
         {"title": "Reproducibility capsule", "id": "repro",
          "summary": "A content-addressed manifest (stable config_hash, secret-free), a determinism check that "
                     "recomputes the persona case-mix and proves it matches, and a bundle a reviewer can keep.",
          "when": "Archiving or verifying a run; filing with a publication.",
          "steps": [{"m": "GET", "p": "/runs/{run_id}/manifest.json", "note": "config + config_hash"},
                    {"m": "GET", "p": "/runs/{run_id}/verify.json", "note": "determinism check"},
                    {"m": "GET", "p": "/runs/{run_id}/capsule.json", "note": "manifest + results + rows"}]},
         {"title": "Pre-registration", "id": "prereg",
          "summary": "An OSF-style protocol (hypotheses, design, outcomes, analysis plan, sample-size "
                     "justification, exclusions, ethics/dual-use) to freeze before the confirmatory run.",
          "when": "Before collecting confirmatory data.",
          "doc": "PREREGISTRATION.md"},
     ]},
    {"stage": "Confirmatory analysis & interop (separate packages)", "anchor": "packages",
     "blurb": "Heavier, offline packages kept out of the stdlib service: the confirmatory statistics and the "
              "UK AISI Inspect surface.",
     "workflows": [
         {"title": "Confirmatory analysis", "id": "analysis",
          "summary": "pandas/statsmodels/lifelines models against the tidy export: GEE logistic, "
                     "Kaplan–Meier + log-rank, discrete-time cloglog hazard, Aalen–Johansen competing risks, "
                     "Benjamini–Hochberg, and a latent-safety leaderboard (Rasch IRT + Bradley–Terry) with a "
                     "forest plot.",
          "when": "The confirmatory statistics for the paper.",
          "cmds": [{"cmd": "cd analysis && pip install -r requirements.txt",
                    "note": "separate heavy environment"},
                   {"cmd": "python -m analysis.cli --input tidy.csv --out results/",
                    "note": "or --simulate for a demo"}]},
         {"title": "Inspect (UK AISI) interop", "id": "inspect",
          "summary": "The eval as a first-class Inspect task + model-graded scorer, runnable in `inspect view`; "
                     "`samples_from_tidy` replays a run's case mix as an Inspect dataset.",
          "when": "Running the eval in the Inspect ecosystem / frontier-lab stack.",
          "cmds": [{"cmd": "cd inspect_eval && pip install -r requirements.txt", "note": ""},
                   {"cmd": "inspect eval clinical_redteam.py --model <model> -T grader=<grader>",
                    "note": "then: inspect view"}]},
     ]},
]


def http_paths() -> list[str]:
    """Every HTTP path referenced by the guide (for the route-coverage test)."""
    out = []
    for g in GROUPS:
        for w in g["workflows"]:
            for s in w.get("steps", []):
                if "p" in s:
                    out.append(s["p"])
    return out


def _badge(method: str) -> str:
    color = {"GET": "#1baf7a", "POST": "#2a78d6"}.get(method, "#52514e")
    return (f'<span style="display:inline-block;min-width:44px;text-align:center;padding:1px 6px;'
            f'border-radius:4px;background:{color};color:#fff;font-size:11px;font-weight:600">{method}</span>')


def _step(s: dict) -> str:
    if "cmd" in s:
        note = f' <span class="muted small">— {escape(s["note"])}</span>' if s.get("note") else ""
        return (f'<div style="margin:3px 0"><code style="background:#f3f2ee;padding:2px 6px;border-radius:4px">'
                f'$ {escape(s["cmd"])}</code>{note}</div>')
    note = f' <span class="muted small">— {escape(s["note"])}</span>' if s.get("note") else ""
    return (f'<div style="margin:3px 0;display:flex;gap:8px;align-items:baseline">{_badge(s["m"])}'
            f'<code style="background:#f3f2ee;padding:2px 6px;border-radius:4px">{escape(s["p"])}</code>{note}</div>')


def _workflow(w: dict) -> str:
    steps = "".join(_step(s) for s in w.get("steps", [])) + "".join(_step(s) for s in w.get("cmds", []))
    if w.get("doc"):
        steps += (f'<div style="margin:3px 0" class="small">Repo document: '
                  f'<code>redteam/{escape(w["doc"])}</code></div>')
    when = (f'<div class="small muted" style="margin-top:4px"><b>When:</b> {escape(w["when"])}</div>'
            if w.get("when") else "")
    return (f'<div style="border:1px solid #e4e3de;border-radius:8px;padding:14px 16px;margin:10px 0;background:#fff">'
            f'<h3 style="margin:0 0 4px">{escape(w["title"])}</h3>'
            f'<p style="margin:0 0 8px">{escape(w["summary"])}</p>{when}'
            f'<div style="margin-top:8px">{steps}</div></div>')


def render_html() -> str:
    from .report import CSS
    toc = " · ".join(f'<a href="#{g["anchor"]}">{escape(g["stage"])}</a>' for g in GROUPS)
    sections = []
    for g in GROUPS:
        cards = "".join(_workflow(w) for w in g["workflows"])
        sections.append(
            f'<h2 id="{g["anchor"]}">{escape(g["stage"])}</h2>'
            f'<p class="muted">{escape(g["blurb"])}</p>{cards}')
    n = sum(len(g["workflows"]) for g in GROUPS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Methods &amp; workflows — sauce.ai/redteam</title>
<style>{CSS}</style></head><body><div class="wrap">
<div class="muted small">sauce.ai/redteam</div>
<h1>Methods &amp; workflows</h1>
<p class="lede">Every capability in the system, grouped by stage of an evaluation study, with the exact
calls to run it. {n} workflows — from pointing the service at a chatbot to the confirmatory statistics.</p>
<p class="small" style="margin-bottom:18px">{toc}</p>
<div class="warn">For authorized testing only. Harm labels are LLM-judge screening signals (the judge is
itself audited), not clinical determinations — a clinician must review flagged transcripts.</div>
{''.join(sections)}
<p class="small muted" style="margin-top:28px">Full design and statistics: <code>redteam/RESEARCH.md</code>
and <code>redteam/PREREGISTRATION.md</code>. Separate packages: <code>redteam/analysis/</code> and
<code>redteam/inspect_eval/</code>.</p>
</div></body></html>"""
