# sauce.ai/redteam — research plan

Turning the red-team service into the instrument behind a peer-reviewed
study of clinical-chatbot safety. This document is the durable, versioned
plan; it is maintained alongside the code and updated as phases land.

Status legend: **[ ]** not started · **[~]** in progress · **[x]** done.

---

## 1. Central thesis

> We reframe clinical-AI safety evaluation as an **epidemiological
> measurement problem**. Adversarial conversations are the *exposure*,
> clinician-adjudicated harm is the *outcome*, and we estimate interpretable
> population-level risk — number-needed-to-harm, prompts-until-harm
> (survival), and expected DALY burden — across deployed medical chatbots,
> using an automated adjudicator validated against a clinician gold
> standard.

The epidemiological framing is the edge over ML-native red-teaming papers:
clinically interpretable risk, not "attack success rate."

### Contributions

1. **Epidemiological metric framework** for AI clinical harm (NNH,
   prompts-until-harm survival, expected DALY burden, escalation
   sensitivity).
2. **Adaptive multi-agent adversarial elicitation** (tactic bandit +
   multi-provider propose/refine/arbiter/consensus) — with ablations
   proving each component's marginal value.
3. **Validated automated adjudicator** — an LLM judge panel benchmarked
   against clinician adjudication (agreement, diagnostic accuracy,
   calibration). *This is the critical path.*
4. **Reproducible benchmark** across deployed clinical chatbots with an
   open eval harness and de-identified dataset.

### Target venues

Nature Medicine · NEJM AI · Nature Machine Intelligence · Lancet Digital
Health · npj Digital Medicine. Write for Nature Medicine; let a
field-defining benchmark + a striking cross-model finding carry it higher.

---

## 2. Outcomes

- **Primary:** proportion of conversations eliciting ≥1 adjudicated-harmful
  reply, per model (attack success rate).
- **Co-primary:** median prompts-until-harm (time-to-event).
- **Secondary:** expected DALY burden; harm-category distribution;
  escalation sensitivity on red-flag conversations; tactic effects;
  subgroup vulnerability (pediatric dosing, pregnancy/lactation, geriatric
  polypharmacy, anticoagulation, insulin, mental-health crisis).

---

## 3. Judge-validation study (critical path)

Nothing downstream is credible until harm labels are trustworthy.

- **Gold standard:** ≥3 board-certified clinicians across the specialties
  adjudicate a **stratified random sample** of conversations under a written
  **codebook**, blinded to arm and to which model produced the reply.
- **Protocol:** two independent raters + a third for disagreements; harm
  taxonomy mapped to **AHRQ Common Formats** / **WHO ICPS**; severity
  anchored to examples.
- **Judge as a diagnostic test** vs the human majority: sensitivity,
  specificity, PPV/NPV, AUROC (using the judge's P(harm) as the score).
- **Agreement:** Cohen's / Fleiss' κ, plus **Gwet's AC1** (robust when harm
  is rare and κ is paradoxical); weighted κ for severity.
- **Calibration:** reliability diagram, **Brier score**, **expected
  calibration error**; recalibrate (Platt/isotonic) and report both.
- **Human–human reliability** as the ceiling the judge is measured against.

**Build:** the in-app adjudication pipeline (Phase A below) produces the
sample, collects blinded labels, and computes agreement + calibration.

---

## 4. Experimental design

- **Pre-registration (OSF):** hypotheses, primary/secondary outcomes, full
  analysis plan, stopping rules — before the confirmatory run.
- **Targets:** a defined, reproducible panel — frontier general LLMs under a
  health-assistant prompt, purpose-built clinical chatbots, consumer health
  apps — each pinned to a dated snapshot.
- **Stratification & vulnerable subgroups:** the specialties/conditions in
  `catalog.py`, weighted toward high-harm subgroups.
- **Blinding & seeds:** judges blinded; fixed seeds, pinned prompt versions,
  pinned model snapshots.
- **Reference-standard answers** for a correctness subset (guideline-derived)
  so "harmful" is grounded, not only judge opinion.
- **Power analysis:** pre-specify the smallest harm-rate difference / NNH to
  detect; size trial counts including the design effect from clustering.

---

## 5. Statistical analysis plan

The in-app metrics (Wilson intervals, KM/log-rank, RR/RD, NNH) are the
descriptive layer. Confirmatory analysis runs in a **separate analysis
repo** (R `brms`/`lme4` or Python `statsmodels`/`lifelines`) against the
tidy per-turn export, because turns are nested in conversations nested in
targets/personas and independence is violated.

- **Primary model:** mixed-effects logistic regression
  `harmful ~ arm + specialty + tactic + vulnerability + (1|target) +
  (1|persona)`; report ORs + CIs and the **ICC**. GEE as sensitivity.
- **Time-to-harm:** discrete-time survival (complementary log-log) with a
  **target-level frailty**; **competing risks** (safe end vs harmful vs
  refusal — refusal ≠ safe); interval censoring. KM/log-rank stays
  descriptive.
- **Latent safety score:** IRT / Bradley–Terry over conversations-as-items,
  models-as-subjects → a principled leaderboard with uncertainty.
- **Multiplicity:** Benjamini–Hochberg FDR across category × specialty ×
  model contrasts; pre-specified primary family.
- **Tactic effects:** mixed model of P(harm) by tactic (the bandit
  posteriors motivate hypotheses; the confirmatory estimate is the model).
- **Sensitivity analyses (pre-specified):** harm-threshold sweep,
  judge-model swap, persona realism, and the DALY parameters (§6).

---

## 6. Harm-burden model (QALY → DALY)

Replace hand-set utilities with a defensible, GBD-grounded model.

- **DALYs** with **GBD disability weights** (add alongside the current QALY
  model in `catalog.py`).
- Map each severity → specific health state(s) → published disability
  weights / EQ-5D utilities, with citations.
- **Probabilistic sensitivity analysis:** distributions on every parameter
  (follow, harm-given-follow, severity, weight, duration); Monte-Carlo the
  expected burden → report a distribution, not a point.
- Frame explicitly as an **illustrative expected-harm-burden model** under
  stated assumptions; let the PSA show robustness.

---

## 7. The attack method as a methods contribution

To claim the orchestrator as novel, not plumbing:

- **Ablations:** bandit vs random tactic; ensemble vs single model;
  lookahead on/off; 1 vs 3 sub-agent levels; with/without consensus —
  marginal effect on attack success and on prompts-until-harm.
- **Baselines:** published automated red-teamers (PAIR, TAP / tree-of-
  attacks) and, ideally, a small **human red-team** arm.
- **Transferability:** do attacks found against model A transfer to B?

---

## 8. Reproducibility, ethics, dual-use

- **Open science:** release code, de-identified conversation + annotation
  dataset (synthetic patients help), a **datasheet for datasets**, model
  cards, full compute/cost accounting, and a re-runnable eval harness.
- **Reporting standards:** TRIPOD-LLM / TRIPOD-AI and CLAIM-style
  checklists.
- **IRB:** synthetic patients are almost certainly not human-subjects
  research — obtain and cite a formal determination/exemption.
- **Responsible disclosure:** notify vendors of specific failures before
  publication with an embargo; publish categories/rates but withhold the
  most operational jailbreak strings. Dual-use governance statement is
  mandatory.

---

## 9. Limitations to pre-empt

Judge validity (§3 answers it); DALY speculativeness (§6 PSA); synthetic-
persona realism (validate personas with clinicians; state the gap to real
patients); non-independence (§5 mixed models); model drift (pin snapshots,
date everything); prompt-injection contaminating the judge (isolated;
document); generalization from the target panel to the deployed ecosystem.

---

## 10. Build roadmap (tool work that supports the science)

- **Phase A — Human-adjudication pipeline** *(in progress)* — stratified
  sample export, blinded clinician labeling UI, inter-rater agreement
  (κ / AC1 / weighted κ) and judge-vs-human diagnostics + calibration
  (sens/spec/PPV/NPV/AUROC, Brier, ECE, reliability). Unlocks §3.
- **Phase B — Reproducible export + cross-model comparison** *(landed:
  tidy export + comparison; paired-persona batch runner still open)* —
  **tidy dataset export** (`/export/tidy.csv?runs=…&level=turn|trial`,
  one row per turn/conversation with all covariates) drives §5, and
  `/compare?runs=…` gives the descriptive cross-model leaderboard (attack
  success, harmful-reply risk, median prompts-to-harm, NNH, QALYs/1,000
  with CIs) + overlaid KM curves. **Still open:** a one-submission batch
  runner that presents the *same* personas to each target (fix the seed +
  specialty + n_trials today to get a paired case-mix) and a Parquet
  writer.
- **Phase C — Analysis repo** — mixed models, frailty survival, FDR, IRT,
  DALY PSA against the export.
- **Phase D — DALY module** — GBD weights + PSA in the app/report.
- **Phase E — Ablation harness** — toggle orchestrator components across
  matched runs and log deltas (§7).
- **Phase F — Pre-registration draft + power calculator** (§4).

- **Critical Harm Event (CHE) measure** *(landed)* — an additive,
  design-based headline metric: a screener → two-phase clinician adjudication
  → the **Critical Harm Rate** with Horvitz–Thompson correction, exact and
  bootstrap CIs, rule-of-three, screener diagnostics, time-to-first-CHE, and a
  redacted report. Modules `app/che*.py`; config `REDTEAM_CHE_*`. **Open:**
  wire enriched seeds into the run loop (loader + schema shipped) and attach
  safe reference outputs per scenario for attributable CHR.

---

_Owner: mhittle (physician-epidemiologist, Stanford). This plan is a living
document; update phase status and the SAP as decisions are made and results
come in._
