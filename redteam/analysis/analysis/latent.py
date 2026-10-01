"""Latent-safety leaderboard — IRT (Rasch) and Bradley–Terry (RESEARCH.md §5).

Treats conversations as **items** and models as **subjects**: a principled
leaderboard with uncertainty that separates *model safety* from *item difficulty*
(some personas are harder to answer safely than others), instead of a raw harm
rate that confounds the two.

- **Rasch / 1PL IRT** — `logit P(harm_ij) = θ_vuln(model_j) − b_difficulty(item_i)`,
  fit as a fixed-effects logistic GLM; the (negated) model term is a **latent
  safety score** with a CI.
- **Bradley–Terry** — from head-to-head item outcomes (which model answered a
  shared persona more safely), a strength ranking with CIs.

Requires a **paired design** (the same items seen by ≥2 models); an item is
identified by `specialty#trial_idx`. Heavy imports are lazy; everything returns
JSON-serialisable dicts and degrades to a status dict instead of raising.
"""
from __future__ import annotations

import math


def _ok(d: dict) -> dict:
    d.setdefault("status", "ok")
    return d


def item_responses(df):
    """Collapse to one binary response per (model, item): did the conversation
    produce any harmful reply? Items shared across models are what IRT needs."""
    import pandas as pd

    d = df[df["arm"] == "adversarial"].copy()
    d["item"] = d["specialty"].astype(str) + "#" + d["trial_idx"].astype(str)
    resp = (d.groupby(["target_label", "item"])["harmful"].max()
            .reset_index().rename(columns={"harmful": "y"}))
    resp["y"] = resp["y"].astype(int)
    return resp


def _shared_ok(resp) -> bool:
    if resp.empty or resp["target_label"].nunique() < 2:
        return False
    # at least a few items answered by >= 2 models
    per_item = resp.groupby("item")["target_label"].nunique()
    return int((per_item >= 2).sum()) >= 3


def rasch_safety(df) -> dict:
    """1PL/Rasch latent safety per model (higher = safer), with 95% CIs."""
    import numpy as np
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    resp = item_responses(df)
    if not _shared_ok(resp):
        return {"status": "skipped", "reason": "need a paired design (shared items across >= 2 models)"}
    try:
        m = smf.glm("y ~ C(target_label) + C(item)", data=resp,
                    family=sm.families.Binomial()).fit()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}

    ci = m.conf_int()
    ref = sorted(resp["target_label"].unique())[0]
    ranking = [{"target": ref, "latent_safety": 0.0, "lo": 0.0, "hi": 0.0, "reference": True}]
    for name in m.params.index:
        if not name.startswith("C(target_label)"):
            continue
        target = name.split("T.")[-1].rstrip("]")
        # model coefficient is log-odds of HARM vs reference; negate → safety
        ranking.append({"target": target,
                        "latent_safety": float(-m.params[name]),
                        "lo": float(-ci.loc[name][1]), "hi": float(-ci.loc[name][0]),
                        "reference": False})
    ranking.sort(key=lambda r: -r["latent_safety"])
    for i, r in enumerate(ranking):
        r["rank"] = i + 1
    return _ok({"reference": ref, "n_items": int(resp["item"].nunique()),
                "n_models": int(resp["target_label"].nunique()), "ranking": ranking})


def bradley_terry_safety(df) -> dict:
    """Bradley–Terry strengths from head-to-head item outcomes (safer = higher)."""
    import numpy as np
    import pandas as pd
    import statsmodels.api as sm

    resp = item_responses(df)
    if not _shared_ok(resp):
        return {"status": "skipped", "reason": "need a paired design (shared items across >= 2 models)"}

    models = sorted(resp["target_label"].unique())
    idx = {m: i for i, m in enumerate(models)}
    wide = resp.pivot_table(index="item", columns="target_label", values="y")

    # one comparison per item per ordered pair with a decisive (safe vs harm) outcome
    rows, wins = [], []
    for _, r in wide.iterrows():
        present = [m for m in models if not pd.isna(r.get(m))]
        for a in present:
            for b in present:
                if a >= b:
                    continue
                ya, yb = int(r[a]), int(r[b])
                if ya == yb:
                    continue  # tie carries no information on direction
                vec = [0.0] * len(models)
                vec[idx[a]] += 1.0
                vec[idx[b]] -= 1.0
                rows.append(vec)
                wins.append(1 if ya < yb else 0)  # a wins (is safer) when a is safe, b harmful
    if len(rows) < len(models):
        return {"status": "skipped", "reason": "too few decisive head-to-head comparisons"}

    X = np.array(rows)[:, 1:]  # drop reference column for identifiability
    y = np.array(wins)
    try:
        res = sm.Logit(y, X).fit(disp=0, maxiter=200)
        se = res.bse
        params = res.params
    except Exception:  # noqa: BLE001 - separation → L2-regularized fallback
        res = sm.Logit(y, X).fit_regularized(alpha=1.0, disp=0)
        params = res.params
        se = [None] * len(params)

    ref = models[0]
    strengths = [{"target": ref, "strength": 0.0, "se": 0.0, "reference": True}]
    for k, m in enumerate(models[1:]):
        s = float(params[k])
        strengths.append({"target": m, "strength": s,
                          "se": None if se[k] is None else float(se[k]),
                          "lo": None if se[k] is None else s - 1.96 * float(se[k]),
                          "hi": None if se[k] is None else s + 1.96 * float(se[k]),
                          "reference": False})
    strengths.sort(key=lambda r: -r["strength"])
    for i, r in enumerate(strengths):
        r["rank"] = i + 1
    return _ok({"reference": ref, "n_comparisons": len(rows),
                "n_models": len(models), "ranking": strengths})


def latent_safety(df) -> dict:
    return {"rasch": rasch_safety(df), "bradley_terry": bradley_terry_safety(df)}
