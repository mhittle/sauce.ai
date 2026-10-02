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


# -- forest plot (pure SVG, no plotting deps) ---------------------------------

def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def forest_svg(rasch: dict, width: int = 720) -> str:
    """A forest plot of the Rasch latent-safety ranking: point estimate + 95% CI
    per model, safest at top, with a reference line at 0 (the reference model).
    Returns an SVG string; empty string if there is nothing to plot."""
    if not rasch or rasch.get("status") != "ok" or not rasch.get("ranking"):
        return ""
    ranking = rasch["ranking"]
    rowh, pad_t, pad_b, pad_l, pad_r = 34, 54, 46, 180, 30
    height = pad_t + rowh * len(ranking) + pad_b
    pw = width - pad_l - pad_r

    los = [r["lo"] for r in ranking if r.get("lo") is not None]
    his = [r["hi"] for r in ranking if r.get("hi") is not None]
    lo_x = min(los + [0.0]) - 0.4
    hi_x = max(his + [0.0]) + 0.4
    span = (hi_x - lo_x) or 1.0

    def x(v: float) -> float:
        return pad_l + pw * (v - lo_x) / span

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
             f'xmlns="http://www.w3.org/2000/svg" style="max-width:{width}px" '
             f'font-family="system-ui,Arial" role="img" '
             f'aria-label="Latent-safety forest plot">',
             f'<rect width="{width}" height="{height}" fill="#fcfcfb"/>',
             f'<text x="{pad_l}" y="26" font-size="16" font-weight="700" fill="#0b0b0b">'
             f'Latent-safety leaderboard (Rasch / 1PL IRT)</text>',
             f'<text x="{pad_l}" y="44" font-size="12" fill="#52514e">'
             f'model safety separated from item difficulty · higher = safer · '
             f'reference {_esc(rasch.get("reference", ""))} = 0</text>']

    # axis grid + zero reference line
    import math
    lo_t, hi_t = math.floor(lo_x), math.ceil(hi_x)
    t = lo_t
    while t <= hi_t:
        gx = x(t)
        parts.append(f'<line x1="{gx:.1f}" x2="{gx:.1f}" y1="{pad_t - 6}" '
                     f'y2="{height - pad_b + 6:.1f}" stroke="#eeede8"/>'
                     f'<text x="{gx:.1f}" y="{height - pad_b + 22:.1f}" font-size="10" '
                     f'text-anchor="middle" fill="#9a9893">{t:+d}</text>')
        t += 1
    zx = x(0.0)
    parts.append(f'<line x1="{zx:.1f}" x2="{zx:.1f}" y1="{pad_t - 6}" '
                 f'y2="{height - pad_b + 6:.1f}" stroke="#b9b7b1" stroke-dasharray="3 3"/>')

    for i, r in enumerate(ranking):
        cy = pad_t + i * rowh + rowh / 2
        safe_hue = max(0.0, min(1.0, 0.5 + r["latent_safety"] / 6))  # green→red by safety
        col = f"hsl({int(120 * safe_hue)},58%,40%)"
        parts.append(f'<text x="{pad_l - 12}" y="{cy + 4:.1f}" font-size="13" '
                     f'text-anchor="end" fill="#0b0b0b">#{r["rank"]} {_esc(r["target"])}</text>')
        if r.get("lo") is not None and r.get("hi") is not None and not r.get("reference"):
            parts.append(f'<line x1="{x(r["lo"]):.1f}" x2="{x(r["hi"]):.1f}" y1="{cy:.1f}" '
                         f'y2="{cy:.1f}" stroke="{col}" stroke-width="2"/>'
                         f'<line x1="{x(r["lo"]):.1f}" x2="{x(r["lo"]):.1f}" y1="{cy - 5:.1f}" '
                         f'y2="{cy + 5:.1f}" stroke="{col}" stroke-width="2"/>'
                         f'<line x1="{x(r["hi"]):.1f}" x2="{x(r["hi"]):.1f}" y1="{cy - 5:.1f}" '
                         f'y2="{cy + 5:.1f}" stroke="{col}" stroke-width="2"/>')
        parts.append(f'<circle cx="{x(r["latent_safety"]):.1f}" cy="{cy:.1f}" r="5" fill="{col}" '
                     f'stroke="#fcfcfb" stroke-width="1.5"/>')
        label = f'{r["latent_safety"]:+.2f}' + ("" if r.get("reference")
                 else f'  [{r["lo"]:+.2f}, {r["hi"]:+.2f}]')
        parts.append(f'<text x="{width - pad_r:.1f}" y="{cy - 8:.1f}" font-size="10" '
                     f'text-anchor="end" fill="#52514e">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)
