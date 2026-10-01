# sauce.ai/redteam — confirmatory analysis

The red-team **service** (`../`) is deliberately pure stdlib: it runs the study
and emits descriptive statistics (Wilson, KM/log-rank, NNH, the Critical Harm
Rate). This **analysis package** is where the *confirmatory* models live
(RESEARCH.md §5, PREREGISTRATION.md §5) — they need the scientific Python stack
(pandas / statsmodels / lifelines), so they are kept out of the service and run
here, offline, against the service's tidy export.

> Nothing in the service imports this package. It is a separate, heavier
> environment on purpose.

## Input

The service's tidy per-turn export — one row per reply, with every covariate:

```
GET /export/tidy.csv?runs=<id>,<id>,…&level=turn      # or /export/tidy.json
```

Fixing the same seed + specialty + n_trials across target runs yields the same
persona case-mix, so targets are compared paired. The expected columns are the
contract in `analysis/schema.py`.

## Install & run

```bash
pip install -r requirements.txt

# against a real export
python -m analysis.cli --input tidy.csv --out results/

# or a runnable demo on synthetic data (no export needed)
python -m analysis.cli --simulate --out results/
```

Outputs `results/results.json` and `results/results.md`.

## What it fits (pre-registered family)

| RQ | Model | Module |
| --- | --- | --- |
| RQ1/H1 — harm differs by target | GEE logistic `harmful ~ target + specialty + tactic`, clustered on the conversation; pooled GLM for reference; random-effects (Bayesian mixed GLM) when it converges | `models.primary_logistic` |
| RQ2/H2 — time to first harm | Kaplan–Meier medians + multivariate log-rank; discrete-time complementary-log-log hazard | `models.km_logrank`, `models.discrete_time_hazard` |
| — competing risks | Aalen–Johansen cumulative incidence for the harmful cause (refusal ≠ safe) | `models.competing_risks` |
| multiplicity | Benjamini–Hochberg across target contrasts | `stats_utils.benjamini_hochberg` |

The latent-safety IRT/Bradley–Terry leaderboard and the DALY probabilistic
sensitivity analysis (RESEARCH.md §5–6) are future additions here.

## Layout & testing

```
analysis/
  schema.py       tidy-export contract + validation   (pure stdlib)
  io.py           CSV/JSON loader; lazy pandas frame   (pure stdlib loader)
  simulate.py     synthetic tidy data with signal      (pure stdlib)
  stats_utils.py  Benjamini–Hochberg FDR              (pure stdlib)
  models.py       statsmodels / lifelines fits         (heavy, lazy imports)
  sap.py          runs the pre-registered family
  cli.py          `python -m analysis.cli`
tests/            stdlib tests + a gated model smoke test
```

- The data layer is unit-tested with no third-party dependency, so it runs
  under the service's stdlib CI.
- The model layer is exercised by the `analysis-ci` workflow (which installs
  this `requirements.txt`) and by the smoke test, which **skips** wherever the
  scientific stack is absent. The smoke test asserts the SAP runs end-to-end on
  simulated data and recovers the planted target ordering, not exact
  coefficients.
