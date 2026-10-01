"""Confirmatory models (PREREGISTRATION.md §5 / RESEARCH.md §5).

Heavy stack (pandas / statsmodels / lifelines) imported lazily inside each
function, so importing this module costs nothing and the data-handling layer
stays usable without the scientific stack. Every fit returns a plain dict of
estimates (JSON-serialisable) and never raises for an expected modelling
condition — it returns ``{"status": "...", "error": ...}`` instead, so the SAP
can report partial results.

These functions are exercised by the `analysis-ci` workflow (which installs the
stack) and by `scripts`/notebooks on the researcher's machine; they are not run
by the stdlib `redteam-ci` check.
"""
from __future__ import annotations

import math


def _ok(d: dict) -> dict:
    d.setdefault("status", "ok")
    return d


def primary_logistic(df) -> dict:
    """RQ1/H1 — does harm differ by target, adjusting for arm/specialty/tactic,
    with turns clustered in conversations?

    Primary: GEE logistic with an exchangeable working correlation clustered on
    the conversation (``trial_id``) — cluster-robust SEs for the within-
    conversation correlation. Reported alongside a pooled GLM for reference. The
    full random-effects fit (``BinomialBayesMixedGLM``) is attempted and recorded
    when it converges, but is not required.
    """
    import numpy as np  # noqa: F401
    import pandas as pd
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    d = df[df["arm"] == "adversarial"].copy()
    if d["target_label"].nunique() < 2:
        return {"status": "skipped", "reason": "need >= 2 targets"}
    d["harmful"] = d["harmful"].astype(int)
    formula = "harmful ~ C(target_label) + C(specialty) + C(tactic)"

    out: dict = {"n": int(len(d)), "n_targets": int(d["target_label"].nunique())}
    # GEE (primary): cluster on conversation
    try:
        gee = smf.gee(formula, groups="trial_id", data=d,
                      family=sm.families.Binomial(),
                      cov_struct=sm.cov_struct.Exchangeable()).fit()
        out["gee"] = _coef_table(gee)
    except Exception as exc:  # noqa: BLE001
        out["gee"] = {"status": "error", "error": str(exc)}
    # pooled GLM (reference)
    try:
        glm = smf.glm(formula, data=d, family=sm.families.Binomial()).fit()
        out["pooled_glm"] = _coef_table(glm)
    except Exception as exc:  # noqa: BLE001
        out["pooled_glm"] = {"status": "error", "error": str(exc)}
    # random-effects (optional)
    try:
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
        vc = {"persona": "0 + C(trial_id)"}
        m = BinomialBayesMixedGLM.from_formula(
            "harmful ~ C(target_label) + C(specialty) + C(tactic)",
            vc_formulas=vc, data=d)
        r = m.fit_vb()
        out["random_effects"] = {"status": "ok",
                                 "params": {k: float(v) for k, v in zip(r.model.exog_names, r.params)}}
    except Exception as exc:  # noqa: BLE001
        out["random_effects"] = {"status": "unavailable", "error": str(exc)[:200]}
    return _ok(out)


def _coef_table(res) -> dict:
    import numpy as np
    params = res.params
    try:
        ci = res.conf_int()
    except Exception:  # noqa: BLE001
        ci = None
    rows = {}
    for name in params.index:
        beta = float(params[name])
        row = {"beta": beta, "or": float(np.exp(beta))}
        try:
            row["p"] = float(res.pvalues[name])
        except Exception:  # noqa: BLE001
            pass
        if ci is not None:
            lo, hi = float(ci.loc[name][0]), float(ci.loc[name][1])
            row["or_lo"], row["or_hi"] = float(np.exp(lo)), float(np.exp(hi))
        rows[name] = row
    return {"status": "ok", "coef": rows}


def km_logrank(df) -> dict:
    """RQ2/H2 — time (prompts) to first harmful reply by target: Kaplan–Meier
    medians + a multivariate log-rank test across targets."""
    import pandas as pd
    from lifelines import KaplanMeierFitter
    from lifelines.statistics import multivariate_logrank_test

    d = _conversation_level(df)
    if d.empty or d["target_label"].nunique() < 2:
        return {"status": "skipped", "reason": "need >= 2 targets with conversations"}
    kmf = KaplanMeierFitter()
    medians = {}
    for target, g in d.groupby("target_label"):
        kmf.fit(g["time"], g["event"])
        med = kmf.median_survival_time_
        medians[str(target)] = None if (med is None or math.isinf(med)) else float(med)
    lr = multivariate_logrank_test(d["time"], d["target_label"], d["event"])
    return _ok({"medians": medians,
                "logrank": {"chi2": float(lr.test_statistic), "p": float(lr.p_value),
                            "df": int(d["target_label"].nunique() - 1)}})


def discrete_time_hazard(df) -> dict:
    """RQ2 — discrete-time (complementary log-log) hazard of first harm per
    prompt, with target as a fixed effect; person-period expansion with
    conversation-clustered robust SEs (target frailty approximated by the fixed
    effect + cluster-robust covariance)."""
    import numpy as np
    import pandas as pd
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    pp = _person_period(df)
    if pp.empty or pp["target_label"].nunique() < 2:
        return {"status": "skipped", "reason": "need >= 2 targets"}
    try:
        m = smf.gee("event ~ C(target_label) + turn_idx", groups="trial_id", data=pp,
                    family=sm.families.Binomial(sm.families.links.CLogLog()),
                    cov_struct=sm.cov_struct.Independence()).fit()
        return _ok(_coef_table(m))
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


def competing_risks(df) -> dict:
    """Competing outcomes per conversation — harmful vs safe-end vs refusal —
    via the Aalen–Johansen cumulative incidence for the harmful cause. Refusals
    are not treated as safe (RESEARCH.md §5)."""
    import pandas as pd
    from lifelines import AalenJohansenFitter

    import numpy as np

    d = _conversation_level(df, with_causes=True)
    if d.empty or (d["event_type"] == 1).sum() == 0:
        return {"status": "skipped", "reason": "no harmful events"}
    out = {}
    for target, g in d.groupby("target_label"):
        if (g["event_type"] == 1).sum() == 0:
            continue
        try:
            ajf = AalenJohansenFitter(calculate_variance=False)
            # prompt indices are integers → many tied event times; Aalen–Johansen
            # requires distinct times, so add tiny deterministic jitter.
            rng = np.random.default_rng(abs(hash(str(target))) % (2**32))
            jitter = rng.uniform(-0.01, 0.01, size=len(g))
            ajf.fit(g["time"].to_numpy() + jitter, g["event_type"], event_of_interest=1)
            cif = ajf.cumulative_density_
            out[str(target)] = {"harmful_cif_final": float(cif.iloc[-1, 0])}
        except Exception as exc:  # noqa: BLE001
            out[str(target)] = {"status": "error", "error": str(exc)[:160]}
    return _ok({"targets": out})


# -- shaping helpers ----------------------------------------------------------

def _conversation_level(df, with_causes: bool = False):
    """One row per adversarial conversation: time = first-harm prompt or the
    (censored) conversation length; event = harm occurred."""
    import pandas as pd

    d = df[df["arm"] == "adversarial"].copy()
    rows = []
    for tid, g in d.groupby("trial_id"):
        g = g.sort_values("turn_idx")
        n_turns = int(g["turn_idx"].max())
        fh = g["first_harm_turn"]
        first_harm = None
        fhv = fh.dropna()
        if len(fhv):
            try:
                first_harm = int(float(fhv.iloc[0]))
            except (ValueError, TypeError):
                first_harm = None
        event = 1 if first_harm else 0
        time = first_harm if first_harm else n_turns
        rec = {"trial_id": tid, "target_label": g["target_label"].iloc[0],
               "time": max(1, int(time)), "event": event}
        if with_causes:
            status = str(g["trial_status"].iloc[0])
            # 1 = harmful, 2 = refusal/error, 0 = safe completion (censored at end)
            rec["event_type"] = 1 if event else (2 if status in ("error", "refused") else 0)
        rows.append(rec)
    return pd.DataFrame(rows)


def _person_period(df):
    """Expand adversarial conversations to one row per prompt up to and including
    the first harm (discrete-time survival format)."""
    import pandas as pd

    d = df[df["arm"] == "adversarial"].copy()
    rows = []
    for tid, g in d.groupby("trial_id"):
        g = g.sort_values("turn_idx")
        target = g["target_label"].iloc[0]
        for _, r in g.iterrows():
            rows.append({"trial_id": tid, "target_label": target,
                         "turn_idx": int(r["turn_idx"]), "event": int(r["harmful"])})
            if int(r["harmful"]) == 1:
                break
    return pd.DataFrame(rows)
