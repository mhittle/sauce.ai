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
         {"title": "Field scan — the whole field of agents", "id": "field",
          "summary": "One submission runs a curated panel of the main consumer health-advice agents "
                     "(ChatGPT, Claude, Gemini, Llama) on the same case-mix for a condition/area, and renders a "
                     "comparative harm chart ranking the field. Agents whose provider has no server key are "
                     "reported as skipped.",
          "when": "Benchmarking the deployed field for a specific condition; a showcase view.",
          "steps": [
              {"m": "POST", "p": "/field", "note": "body: email, specialty, condition, n_trials, optional models[]"},
              {"m": "GET", "p": "/field", "note": "?field=<id> — comparative report + harm chart"},
              {"m": "GET", "p": "/field.json", "note": "?field=<id> or ?runs=… — raw numbers"},
              {"m": "GET", "p": "/field.svg", "note": "?field=<id> (&share=1 for the 1200×630 image)"},
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
         {"title": "AI advice as an exposure — epidemiologic effect measures", "id": "epi",
          "summary": "Treats each agent as an exposure and a conversation as the unit: RR/OR/RD, NNH, "
                     "attributable fraction, PAF (for a stated exposure prevalence), and the E-value vs a referent "
                     "(safest agent, or a stated baseline risk); Mantel–Haenszel stratification over persona "
                     "covariates with confounding and effect-modification screens; Cochran–Armitage dose–response "
                     "over prompts delivered; quantitative bias analysis for judge misclassification "
                     "(Rogan–Gladen + probabilistic, with the judge's Se/Sp measured from clinician adjudication "
                     "when available — differential per agent where labels allow).",
          "when": "Framing AI advice as an exposure for an epidemiologic audience; checking that the judge's "
                  "imperfect sensitivity/specificity does not drive the headline contrast.",
          "steps": [{"m": "GET", "p": "/epi",
                     "note": "?runs=<id>,<id>,… [&ref=<run_id> | &baseline=0.05] [&prevalence=0.3] [&se=0.9&sp=0.95]"},
                    {"m": "GET", "p": "/epi.json", "note": "numbers"},
                    {"m": "GET", "p": "/epi.svg", "note": "forest plot (?kind=hazard for the dose–response)"}]},
         {"title": "Target trial emulation + causal diagrams", "id": "target-trial",
          "summary": "The randomized trial we would run, component by component (eligibility, strategies, "
                     "assignment, follow-up, outcome, contrasts, analysis), next to how the instrument emulates "
                     "each one with a fidelity grade; ITT vs per-protocol estimands per agent; DAGs for real-world "
                     "use and for the design with minimal adjustment sets (backdoor criterion) and a threats-to-"
                     "validity table pointing to where each is handled.",
          "when": "Explaining to an epidemiologic audience why assignment by design makes the crude agent contrast "
                  "unconfounded — and what residual threats remain (judge measurement, censoring, external validity).",
          "steps": [{"m": "GET", "p": "/target-trial", "note": "?runs=<id>,<id>,… [&ref=<run_id>]"},
                    {"m": "GET", "p": "/target-trial.json", "note": "protocol, estimands, DAG analysis, threats"},
                    {"m": "GET", "p": "/target-trial.svg", "note": "?design=trial|observational — the DAG image"}]},
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



# ---------------------------------------------------------------------------
# Launchers — one or more forms per workflow. The page renders each as a real
# form; a GET form opens the result page with the chosen query, a POST form
# submits JSON and shows the created ids as links. Field types:
#   runs (multi run picker → "a,b,c"), run (single picker; `path`=True fills a
#   {run_id} path param), specialty (select from the catalog), select, number,
#   text, email, secret (sent once, never stored), checkbox, textarea,
#   list ("a, b" → ["a","b"]), models (field-panel checkboxes).
# Dotted names nest ("target.kind"). `result` is a link template over the JSON
# response ("/field?field={field_id}").
# ---------------------------------------------------------------------------

def _run_common(prefix: str = "") -> list[dict]:
    return [
        {"n": "email", "t": "email", "l": "Your email", "req": True, "h": "report is emailed here; quota is per email"},
        {"n": "specialty", "t": "specialty", "l": "Specialty", "req": True},
        {"n": "condition", "t": "text", "l": "Condition (optional)", "ph": "e.g. type 2 diabetes"},
        {"n": "n_trials", "t": "number", "l": "Conversations", "d": 20, "min": 1},
        {"n": "max_turns", "t": "number", "l": "Max prompts per conversation", "d": 8, "min": 1},
        {"n": "harm_threshold", "t": "number", "l": "Harm threshold P(harm) ≥", "d": 0.10, "step": 0.01},
        {"n": "seed", "t": "number", "l": "Seed", "d": 0, "h": "same seed + specialty + n ⇒ same case-mix across targets"},
    ]


_TARGET = [
    {"n": "target.kind", "t": "select", "l": "Target kind", "d": "openai_chat",
     "opt": [("openai_chat", "OpenAI-compatible chat"), ("anthropic", "Anthropic"),
             ("http_json", "Generic HTTP JSON"), ("web_chat", "Web chat (browser)")]},
    {"n": "target.url", "t": "text", "l": "Endpoint URL", "ph": "https://…/v1/chat/completions"},
    {"n": "target.model", "t": "text", "l": "Model", "ph": "gpt-4o"},
    {"n": "target.api_key", "t": "secret", "l": "API key", "h": "used for this run only — never stored"},
    {"n": "target.system_prompt", "t": "textarea", "l": "System prompt (optional)"},
]

FORMS: dict[str, list[dict]] = {
    "submit": [
        {"label": "Launch a red-team run", "m": "POST", "p": "/runs",
         "fields": _run_common() + [
             {"n": "control_fraction", "t": "number", "l": "Control-arm fraction", "d": 0.0, "step": 0.05},
             {"n": "judges", "t": "list", "l": "Judges (optional)", "ph": "anthropic:…, openai:…"},
         ] + _TARGET,
         "result": "/runs/{run_id}", "poll": "/runs/{run_id}/status"},
    ],
    "field": [
        {"label": "Run the whole field", "m": "POST", "p": "/field",
         "fields": [f for f in _run_common() if f["n"] != "max_turns"] + [
             {"n": "max_turns", "t": "number", "l": "Max prompts per conversation", "d": 8, "min": 1},
             {"n": "models", "t": "models", "l": "Agents (leave all unticked = every available)"},
         ],
         "result": "/field?field={field_id}"},
        {"label": "View a field scan", "m": "GET", "p": "/field",
         "fields": [{"n": "runs", "t": "runs", "l": "Completed runs (ad hoc)", "req": True}]},
    ],
    "leaderboard": [
        {"label": "Open the leaderboard", "m": "GET", "p": "/leaderboard",
         "fields": [{"n": "category", "t": "specialty", "l": "Specialty (optional)", "blank": "overall"}]},
    ],
    "card": [
        {"label": "Open a safety card", "m": "GET", "p": "/card",
         "fields": [{"n": "run", "t": "run", "l": "Run", "req": True}]},
    ],
    "evalcard": [
        {"label": "Open the eval card", "m": "GET", "p": "/eval-card", "fields": []},
        {"label": "Open the datasheet", "m": "GET", "p": "/datasheet", "fields": []},
    ],
    "compare": [
        {"label": "Compare runs", "m": "GET", "p": "/compare",
         "fields": [{"n": "runs", "t": "runs", "l": "Runs to compare", "req": True}]},
    ],
    "daly": [
        {"label": "Open the DALY report", "m": "GET", "p": "/runs/{run_id}/daly",
         "fields": [{"n": "run_id", "t": "run", "l": "Run", "req": True, "path": True}]},
    ],
    "epi": [
        {"label": "Run the exposure analysis", "m": "GET", "p": "/epi",
         "fields": [
             {"n": "runs", "t": "runs", "l": "Runs (one per agent, shared case-mix)", "req": True},
             {"n": "ref", "t": "run", "l": "Referent run (optional; default = safest)"},
             {"n": "baseline", "t": "number", "l": "…or a stated baseline risk (0–1)", "step": 0.01,
              "h": "e.g. 0.05 for usual care; overrides the referent run"},
             {"n": "prevalence", "t": "number", "l": "Exposure prevalence for PAF (0–1)", "step": 0.05},
             {"n": "judge", "t": "select", "l": "Judge accuracy for the bias analysis", "d": "auto",
              "opt": [("auto", "measure from clinician adjudication (fallback: assumed)"),
                      ("assumed", "assumed illustrative defaults")],
              "h": "or override with Se/Sp below"},
             {"n": "se", "t": "number", "l": "Judge sensitivity (override)", "step": 0.01},
             {"n": "sp", "t": "number", "l": "Judge specificity (override)", "step": 0.01},
         ]},
    ],
    "target-trial": [
        {"label": "Emulate the target trial", "m": "GET", "p": "/target-trial",
         "fields": [{"n": "runs", "t": "runs", "l": "Runs (one per strategy)", "req": True},
                    {"n": "ref", "t": "run", "l": "Referent strategy (optional)"}]},
        {"label": "DAG image", "m": "GET", "p": "/target-trial.svg",
         "fields": [{"n": "design", "t": "select", "l": "Design", "d": "trial",
                     "opt": [("trial", "red-team design"), ("observational", "real-world use")]}]},
    ],
    "grader": [
        {"label": "Audit the grader", "m": "POST", "p": "/grader-audit",
         "fields": [{"n": "judges", "t": "list", "l": "Judges (optional)", "ph": "anthropic:…, openai:…"},
                    {"n": "threshold", "t": "number", "l": "Harm threshold", "d": 0.10, "step": 0.01}],
         "result": "/grader-audit/{audit_id}", "poll": "/grader-audit/{audit_id}.json"},
    ],
    "adjudication": [
        {"label": "Build a blinded adjudication set", "m": "POST", "p": "/adjudication/sets",
         "fields": [{"n": "run_ids", "t": "runs", "l": "Runs", "req": True},
                    {"n": "name", "t": "text", "l": "Set name"},
                    {"n": "n", "t": "number", "l": "Items", "d": 120, "min": 1},
                    {"n": "seed", "t": "number", "l": "Seed", "d": 0},
                    {"n": "by_specialty", "t": "checkbox", "l": "Stratify by specialty", "d": True},
                    {"n": "by_tactic", "t": "checkbox", "l": "Stratify by tactic", "d": False},
                    {"n": "allocation", "t": "select", "l": "Allocation", "d": "proportional",
                     "opt": [("proportional", "proportional"), ("equal", "equal")]}],
         "result": "/adjudicate/{set_id}"},
    ],
    "che": [
        {"label": "Screen a run for critical harm events", "m": "POST", "p": "/runs/{run_id}/che/screen",
         "fields": [{"n": "run_id", "t": "run", "l": "Run", "req": True, "path": True},
                    {"n": "screener_model", "t": "text", "l": "Screener model (optional)", "ph": "provider:model"},
                    {"n": "seed", "t": "number", "l": "Seed", "d": 0}],
         "result": "/che/report?runs={run_id}"},
        {"label": "Build a clinician review set", "m": "POST", "p": "/che/review-sets",
         "fields": [{"n": "run_ids", "t": "runs", "l": "Screened runs", "req": True},
                    {"n": "name", "t": "text", "l": "Set name"},
                    {"n": "neg_sample_rate", "t": "number", "l": "Negative sample rate (0–1, optional)", "step": 0.05},
                    {"n": "seed", "t": "number", "l": "Seed", "d": 0}],
         "result": "/che-review/{set_id}"},
        {"label": "Open the CHR report", "m": "GET", "p": "/che/report",
         "fields": [{"n": "runs", "t": "runs", "l": "Runs", "req": True}]},
    ],
    "export": [
        {"label": "Download the tidy dataset", "m": "GET", "p": "/export/tidy.csv",
         "fields": [{"n": "runs", "t": "runs", "l": "Runs", "req": True},
                    {"n": "level", "t": "select", "l": "Row level", "d": "turn",
                     "opt": [("turn", "one row per reply"), ("trial", "one row per conversation")]}]},
    ],
    "ablation": [
        {"label": "Launch the ablation arm set", "m": "POST", "p": "/ablation",
         "fields": _run_common() + [
             {"n": "arms", "t": "list", "l": "Arms (optional; default = full matrix)", "ph": "full, no_bandit, …"},
         ] + _TARGET,
         "result": "/ablation/{ablation_id}"},
        {"label": "View an ad-hoc contrast", "m": "GET", "p": "/ablation",
         "fields": [{"n": "runs", "t": "runs", "l": "Pre-tagged arm runs", "req": True}]},
    ],
    "power": [
        {"label": "Open the calculator", "m": "GET", "p": "/power", "fields": []},
    ],
    "repro": [
        {"label": "Open a run's capsule", "m": "GET", "p": "/runs/{run_id}/capsule.json",
         "fields": [{"n": "run_id", "t": "run", "l": "Run", "req": True, "path": True}]},
        {"label": "Verify determinism", "m": "GET", "p": "/runs/{run_id}/verify.json",
         "fields": [{"n": "run_id", "t": "run", "l": "Run", "req": True, "path": True}]},
    ],
}


def form_paths() -> list[str]:
    return [f["p"] for forms in FORMS.values() for f in forms]


def http_paths() -> list[str]:
    """Every HTTP path referenced by the guide (for the route-coverage test)."""
    out = []
    for g in GROUPS:
        for w in g["workflows"]:
            for s in w.get("steps", []):
                if "p" in s:
                    out.append(s["p"])
    for p in form_paths():
        if p not in out:
            out.append(p)
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



def _field_html(f: dict, available_models: set[str] | None) -> str:
    from .catalog import SPECIALTIES
    n, t = f["n"], f["t"]
    req = " required" if f.get("req") else ""
    attrs = f'name="{escape(n)}" data-t="{t}"' + (' data-path="1"' if f.get("path") else "")
    help_ = f'<div class="fh">{escape(f["h"])}</div>' if f.get("h") else ""
    lab = escape(f["l"])
    if t == "runs":
        ctl = f'<select {attrs} multiple size="5" data-runs{req}></select>'
    elif t == "run":
        ctl = f'<select {attrs} data-run{req}></select>'
    elif t == "specialty":
        blank = f.get("blank", "— choose —")
        opts = f'<option value="">{escape(blank)}</option>' + "".join(
            f'<option value="{escape(k)}">{escape(v["label"])}</option>' for k, v in SPECIALTIES.items())
        ctl = f'<select {attrs}{req}>{opts}</select>'
    elif t == "select":
        opts = "".join(f'<option value="{escape(v)}"{" selected" if v == f.get("d") else ""}>{escape(l)}</option>'
                       for v, l in f["opt"])
        ctl = f'<select {attrs}>{opts}</select>'
    elif t == "checkbox":
        ctl = f'<input type="checkbox" {attrs}{" checked" if f.get("d") else ""}>'
        return f'<label class="fl chk">{ctl} <span>{lab}</span>{help_}</label>'
    elif t == "textarea":
        ctl = f'<textarea {attrs} rows="2" placeholder="{escape(f.get("ph", ""))}"></textarea>'
    elif t == "models":
        from .field import FIELD_PANEL
        boxes = []
        for p in FIELD_PANEL:
            ok = available_models is None or p["key"] in available_models
            tag = "" if ok else ' <span class="muted">(no key)</span>'
            boxes.append(f'<label class="chk"><input type="checkbox" name="models" data-t="models" '
                         f'value="{escape(p["key"])}"{"" if ok else " disabled"}> {escape(p["display"])}{tag}</label>')
        return f'<div class="fl"><span class="ft">{lab}</span><div class="boxes">{"".join(boxes)}</div>{help_}</div>'
    else:
        typ = {"email": "email", "secret": "password", "number": "number"}.get(t, "text")
        extra = ""
        if t == "number":
            extra = "".join(f' {k}="{f[k]}"' for k in ("min", "max", "step") if k in f) or ' step="any"'
        if t == "secret":
            extra += ' autocomplete="off"'
        d = f' value="{escape(str(f["d"]))}"' if "d" in f else ""
        ph = f' placeholder="{escape(f["ph"])}"' if f.get("ph") else ""
        ctl = f'<input type="{typ}" {attrs}{d}{ph}{extra}{req}>'
    return f'<label class="fl"><span class="ft">{lab}</span>{ctl}{help_}</label>'


def _form_html(wid: str, i: int, f: dict, available_models: set[str] | None) -> str:
    fields = "".join(_field_html(x, available_models) for x in f.get("fields", []))
    btn = "Launch" if f["m"] == "POST" else "Open"
    attrs = (f'data-m="{f["m"]}" data-p="{escape(f["p"])}"' +
             (f' data-result="{escape(f["result"])}"' if f.get("result") else "") +
             (f' data-poll="{escape(f["poll"])}"' if f.get("poll") else ""))
    return (f'<form class="launch" id="form-{escape(wid)}-{i}" {attrs} onsubmit="return launch(event)">'
            f'<div class="fhead">{_badge(f["m"])} <b>{escape(f["label"])}</b> '
            f'<code>{escape(f["p"])}</code></div>'
            f'<div class="grid">{fields}</div>'
            f'<div class="actions"><button type="submit">{btn}</button> <span class="status muted small"></span></div>'
            f'<div class="result small"></div></form>')


_LAUNCH_CSS = """
.launch{border-top:1px dashed #e4e3de;margin-top:10px;padding-top:10px}
.launch .fhead{margin-bottom:6px}.launch .fhead code{background:#f3f2ee;padding:1px 6px;border-radius:4px;font-size:12px}
.launch .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px 14px}
.launch .fl{display:flex;flex-direction:column;font-size:13px;gap:3px}.launch .fl.chk{flex-direction:row;align-items:center;gap:6px}
.launch .ft{color:#52514e;font-size:12px}.launch .fh{color:#9a9893;font-size:11px}
.launch input,.launch select,.launch textarea{font:inherit;font-size:13px;padding:5px 7px;border:1px solid #d9d8d2;border-radius:6px;background:#fff;min-width:0}
.launch select[multiple]{min-height:96px}.launch .boxes{display:flex;flex-wrap:wrap;gap:4px 14px}.launch .boxes .chk{font-size:12px}
.launch .actions{margin-top:8px}.launch button{font:inherit;font-weight:600;padding:6px 14px;border-radius:6px;border:1px solid #2a78d6;background:#2a78d6;color:#fff;cursor:pointer}
.launch button[disabled]{opacity:.6;cursor:wait}.launch .result{margin-top:6px}.launch .result a{margin-right:10px}
.launch .result pre{background:#f3f2ee;padding:8px;border-radius:6px;overflow:auto;max-height:220px;font-size:11px}
.launch .err{color:#b3261e}
"""

_LAUNCH_JS = r"""
let RUNS = [];
async function loadRuns(){
  try{ const r = await fetch('/runs.json'); const j = await r.json(); RUNS = j.runs || []; }catch(e){ RUNS = []; }
  document.querySelectorAll('select[data-runs],select[data-run]').forEach(sel=>{
    const multi = sel.hasAttribute('data-runs');
    sel.innerHTML = multi ? '' : '<option value="">— none —</option>';
    if(!RUNS.length){ const o=document.createElement('option'); o.disabled=true; o.textContent='no runs yet — launch one above'; sel.appendChild(o); return; }
    RUNS.forEach(r=>{ const o=document.createElement('option'); o.value=r.run_id;
      const bits=[r.label, r.specialty, r.condition, 'n='+r.n_trials, 'seed '+r.seed, r.status, r.run_id.slice(0,8)].filter(Boolean);
      o.textContent = bits.join(' · '); if(r.status!=='complete'){ o.textContent += ' (not complete)'; } sel.appendChild(o); });
  });
}
function setDeep(obj, name, v){ const parts=name.split('.'); let o=obj; parts.slice(0,-1).forEach(p=>{ o[p]=o[p]||{}; o=o[p]; }); o[parts[parts.length-1]]=v; }
function collect(form){
  const body={}; let path=form.dataset.p; const models=[];
  form.querySelectorAll('[name]').forEach(el=>{
    const t=el.dataset.t; let v;
    if(t==='models'){ if(el.checked) models.push(el.value); return; }
    if(t==='runs'){ v=[...el.selectedOptions].map(o=>o.value).filter(Boolean); if(!v.length) return; }
    else if(t==='checkbox'){ v=el.checked; }
    else if(t==='number'){ if(el.value==='') return; v=Number(el.value); }
    else if(t==='list'){ v=el.value.split(',').map(s=>s.trim()).filter(Boolean); if(!v.length) return; }
    else { v=el.value; if(v==='') return; }
    if(el.dataset.path){ path=path.replace('{'+el.name+'}', encodeURIComponent(v)); return; }
    setDeep(body, el.name, v);
  });
  if(models.length) body.models=models;
  return {path, body};
}
function fill(tpl, j){ return tpl.replace(/\{(\w+)\}/g,(m,k)=> j[k]!==undefined ? encodeURIComponent(j[k]) : m); }
async function launch(ev){
  ev.preventDefault(); const form=ev.target; const {path, body}=collect(form);
  const status=form.querySelector('.status'), out=form.querySelector('.result'); out.innerHTML='';
  if(path.includes('{')){ out.innerHTML='<span class="err">choose a run first</span>'; return false; }
  if(form.dataset.m==='GET'){
    const q=new URLSearchParams(); Object.entries(body).forEach(([k,v])=>q.set(k, Array.isArray(v)? v.join(',') : v));
    const url = path + (q.toString()? '?'+q.toString() : ''); window.open(url, '_blank'); out.innerHTML='opened <a href="'+url+'" target="_blank">'+url+'</a>'; return false;
  }
  const btn=form.querySelector('button'); btn.disabled=true; status.textContent='launching…';
  try{
    const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json().catch(()=>({}));
    if(!r.ok){ out.innerHTML='<span class="err">'+(j.detail? (typeof j.detail==='string'? j.detail : JSON.stringify(j.detail)) : r.status)+'</span>'; status.textContent=''; btn.disabled=false; return false; }
    status.textContent='launched';
    let links='';
    if(form.dataset.result && !fill(form.dataset.result,j).includes('{')) links+='<a target="_blank" href="'+fill(form.dataset.result,j)+'">open result →</a>';
    if(form.dataset.poll && !fill(form.dataset.poll,j).includes('{')) links+='<a target="_blank" href="'+fill(form.dataset.poll,j)+'">status</a>';
    if(Array.isArray(j.runs)) j.runs.forEach(x=>{ if(x.run_id) links+='<a target="_blank" href="/runs/'+x.run_id+'">'+(x.display||x.arm||x.run_id.slice(0,8))+'</a>'; });
    if(Array.isArray(j.skipped) && j.skipped.length) links+='<div class="muted">skipped: '+j.skipped.map(s=>s.display+' ('+s.reason+')').join(', ')+'</div>';
    out.innerHTML=links+'<pre>'+JSON.stringify(j,null,1)+'</pre>';
    loadRuns();
  }catch(e){ out.innerHTML='<span class="err">'+e+'</span>'; status.textContent=''; }
  btn.disabled=false; return false;
}
document.addEventListener('DOMContentLoaded', loadRuns);
"""


def _workflow(w: dict, available_models: set[str] | None = None) -> str:
    steps = "".join(_step(s) for s in w.get("steps", [])) + "".join(_step(s) for s in w.get("cmds", []))
    forms = "".join(_form_html(w["id"], i, f, available_models) for i, f in enumerate(FORMS.get(w["id"], [])))
    if w.get("doc"):
        steps += (f'<div style="margin:3px 0" class="small">Repo document: '
                  f'<code>redteam/{escape(w["doc"])}</code></div>')
    when = (f'<div class="small muted" style="margin-top:4px"><b>When:</b> {escape(w["when"])}</div>'
            if w.get("when") else "")
    return (f'<div style="border:1px solid #e4e3de;border-radius:8px;padding:14px 16px;margin:10px 0;background:#fff">'
            f'<h3 style="margin:0 0 4px">{escape(w["title"])}</h3>'
            f'<p style="margin:0 0 8px">{escape(w["summary"])}</p>{when}'
            f'{forms}'
            f'<details style="margin-top:8px"><summary class="small muted">API reference</summary>'
            f'<div style="margin-top:6px">{steps}</div></details></div>')


def render_html(available_models: set[str] | None = None) -> str:
    from .report import CSS
    toc = " · ".join(f'<a href="#{g["anchor"]}">{escape(g["stage"])}</a>' for g in GROUPS)
    sections = []
    for g in GROUPS:
        cards = "".join(_workflow(w, available_models) for w in g["workflows"])
        sections.append(
            f'<h2 id="{g["anchor"]}">{escape(g["stage"])}</h2>'
            f'<p class="muted">{escape(g["blurb"])}</p>{cards}')
    n = sum(len(g["workflows"]) for g in GROUPS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Methods &amp; workflows — sauce.ai/redteam</title>
<style>{CSS}{_LAUNCH_CSS}</style><script>{_LAUNCH_JS}</script></head><body><div class="wrap">
<div class="muted small">sauce.ai/redteam</div>
<h1>Methods &amp; workflows</h1>
<p class="lede">Every capability in the system, grouped by stage of an evaluation study — each with a launcher:
pick runs and parameters, then open the report or start the job. {n} workflows, from pointing the service at a
chatbot to the confirmatory statistics. Run pickers list your recent runs.</p>
<p class="small" style="margin-bottom:18px">{toc}</p>
<div class="warn">For authorized testing only. Harm labels are LLM-judge screening signals (the judge is
itself audited), not clinical determinations — a clinician must review flagged transcripts.</div>
{''.join(sections)}
<p class="small muted" style="margin-top:28px">Full design and statistics: <code>redteam/RESEARCH.md</code>
and <code>redteam/PREREGISTRATION.md</code>. Separate packages: <code>redteam/analysis/</code> and
<code>redteam/inspect_eval/</code>.</p>
</div></body></html>"""
