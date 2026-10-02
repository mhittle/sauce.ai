"""AI advice as an exposure — classical epidemiologic effect measures over
red-team runs (pure stdlib).

Framing: each AI agent is an **exposure**; a conversation is the unit; the
outcome is "elicited unsafe advice" (conversation-level harm). Agents are
contrasted against a **referent** — by default the safest agent in the set
(so measures read as *excess* harm vs the best available advice), or a
user-stated counterfactual baseline risk (e.g. usual care) via `baseline=`.

What this module adds on top of the descriptive comparison:

* **2×2 effect measures** per exposure: risk ratio (Katz log CI), odds ratio
  (Woolf), risk difference (Newcombe), NNH, attributable fraction among the
  exposed, population attributable fraction for a stated exposure prevalence
  (Levin), and the **E-value** (VanderWeele & Ding) for unmeasured confounding.
* **Stratified analysis** over persona covariates (age band, health literacy,
  sex, speaker, affect, access): Mantel–Haenszel pooled RR with the
  Greenland–Robins variance, a crude-vs-adjusted **confounding** flag
  (>10 % change), and Cochran's Q across strata as an **effect-modification**
  screen.
* **Dose–response**: prompts delivered as the dose; discrete-time per-prompt
  harm hazard by turn with a **Cochran–Armitage trend test**.
* **Quantitative bias analysis** for outcome misclassification by the LLM
  judge: Rogan–Gladen correction with the judge's sensitivity/specificity and
  a probabilistic (Monte-Carlo) version yielding a simulation interval.

All labels are LLM-judge screening signals; the QBA section is how that
imperfect test propagates into the effect measures. Nothing here is a
clinical determination.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from html import escape

from . import metrics
from .dataset import target_label

Z95 = 1.959964


# ---------------------------------------------------------------------------
# Small numerics
# ---------------------------------------------------------------------------

def _gammainc_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes gser/gcf)."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-14:
                break
        return max(0.0, 1.0 - s * math.exp(-x + a * math.log(x) - math.lgamma(a)))
    b, c, d = x + 1 - a, 1e300, 1 / (x + 1 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def chi2_sf(x: float, df: int) -> float:
    return _gammainc_q(df / 2.0, max(0.0, x) / 2.0)


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


# ---------------------------------------------------------------------------
# 2×2 measures
# ---------------------------------------------------------------------------

def odds_ratio(a: int, n1: int, c: int, n2: int, z: float = Z95) -> dict:
    """Woolf logit interval; Haldane 0.5 correction when any cell is empty."""
    b, d = n1 - a, n2 - c
    if n1 <= 0 or n2 <= 0:
        return {"value": None, "lo": None, "hi": None}
    corr = 0.5 if 0 in (a, b, c, d) else 0.0
    a_, b_, c_, d_ = a + corr, b + corr, c + corr, d + corr
    or_ = (a_ * d_) / (b_ * c_)
    se = math.sqrt(1 / a_ + 1 / b_ + 1 / c_ + 1 / d_)
    return {"value": or_, "lo": math.exp(math.log(or_) - z * se), "hi": math.exp(math.log(or_) + z * se),
            "continuity_corrected": bool(corr)}


def e_value(rr: float | None, lo: float | None = None, hi: float | None = None) -> dict:
    """E-value (VanderWeele & Ding 2017): the minimum strength of association an
    unmeasured confounder would need with both exposure and outcome to explain
    away the observed RR. Also for the CI limit closest to the null (1 if the
    interval covers 1)."""
    def ev(r):
        if r is None or r <= 0:
            return None
        r = r if r >= 1 else 1 / r
        return r + math.sqrt(r * (r - 1))
    if rr is None:
        return {"point": None, "ci": None}
    if lo is None or hi is None:
        return {"point": ev(rr), "ci": None}
    if lo <= 1 <= hi:
        bound = 1.0
    else:
        bound = lo if rr >= 1 else hi
    return {"point": ev(rr), "ci": ev(bound)}


def attributable_fraction_exposed(rr: float | None) -> float | None:
    """AF_e = (RR − 1) / RR — share of harm among the exposed due to exposure."""
    if rr is None or rr <= 0:
        return None
    return (rr - 1) / rr


def population_attributable_fraction(rr: float | None, prevalence: float | None) -> float | None:
    """Levin's PAF = p(RR−1) / (1 + p(RR−1)) for exposure prevalence p."""
    if rr is None or prevalence is None:
        return None
    x = prevalence * (rr - 1)
    return x / (1 + x) if (1 + x) != 0 else None


def two_by_two(a: int, n1: int, c: int, n2: int, prevalence: float | None = None) -> dict:
    """All effect measures for exposed (a/n1) vs unexposed (c/n2)."""
    p1 = metrics.wilson(a, n1)
    p0 = metrics.wilson(c, n2)
    rr = metrics.risk_ratio(a, n1, c, n2)
    rd = metrics.risk_difference(a, n1, c, n2)
    return {
        "exposed": {"cases": a, "n": n1, "risk": {"value": p1[0], "lo": p1[1], "hi": p1[2]}},
        "unexposed": {"cases": c, "n": n2, "risk": {"value": p0[0], "lo": p0[1], "hi": p0[2]}},
        "risk_ratio": rr, "odds_ratio": odds_ratio(a, n1, c, n2), "risk_difference": rd,
        "nnh": metrics.nnh_from_rd(rd),
        "af_exposed": attributable_fraction_exposed(rr["value"]),
        "paf": population_attributable_fraction(rr["value"], prevalence),
        "e_value": e_value(rr["value"], rr["lo"], rr["hi"]),
    }


def versus_baseline(a: int, n1: int, p0: float, prevalence: float | None = None) -> dict:
    """Exposed risk vs a stated counterfactual baseline risk p0 (treated as fixed):
    the 'AI advice vs usual care' framing when no unexposed arm was run."""
    p, lo, hi = metrics.wilson(a, n1)
    if p0 <= 0 or n1 <= 0:
        rr = {"value": None, "lo": None, "hi": None}
    else:
        rr = {"value": p / p0, "lo": lo / p0, "hi": hi / p0}
    rd = {"value": p - p0, "lo": lo - p0, "hi": hi - p0}
    return {"exposed": {"cases": a, "n": n1, "risk": {"value": p, "lo": lo, "hi": hi}},
            "unexposed": {"cases": None, "n": None, "risk": {"value": p0, "lo": None, "hi": None},
                          "assumed": True},
            "risk_ratio": rr, "odds_ratio": None, "risk_difference": rd, "nnh": metrics.nnh_from_rd(rd),
            "af_exposed": attributable_fraction_exposed(rr["value"]),
            "paf": population_attributable_fraction(rr["value"], prevalence),
            "e_value": e_value(rr["value"], rr["lo"], rr["hi"])}


# ---------------------------------------------------------------------------
# Stratified analysis — Mantel–Haenszel + heterogeneity
# ---------------------------------------------------------------------------

def mantel_haenszel_rr(strata: list[tuple[int, int, int, int]], z: float = Z95) -> dict:
    """strata: (a, n1, c, n2) per stratum. Pooled RR with the Greenland–Robins
    (1985) variance; Cochran's Q on stratum log-RRs as a homogeneity test."""
    use = [(a, n1, c, n2) for a, n1, c, n2 in strata if n1 > 0 and n2 > 0]
    if not use:
        return {"value": None, "lo": None, "hi": None, "n_strata": 0, "q": None, "q_p": None, "strata": []}
    num = sum(a * n2 / (n1 + n2) for a, n1, c, n2 in use)
    den = sum(c * n1 / (n1 + n2) for a, n1, c, n2 in use)
    if num <= 0 or den <= 0:
        return {"value": None, "lo": None, "hi": None, "n_strata": len(use), "q": None, "q_p": None,
                "strata": []}
    rr = num / den
    v = sum((n1 * n2 * (a + c) - a * c * (n1 + n2)) / (n1 + n2) ** 2 for a, n1, c, n2 in use) / (num * den)
    se = math.sqrt(max(v, 0.0))
    # homogeneity: inverse-variance Q on stratum log RRs (0.5-corrected)
    rows, q = [], 0.0
    pts = []
    for a, n1, c, n2 in use:
        r = metrics.risk_ratio(a, n1, c, n2)
        rows.append({"a": a, "n1": n1, "c": c, "n2": n2, "rr": r})
        if r["value"] and r["lo"] and r["hi"] and r["lo"] > 0:
            w = 1 / ((math.log(r["hi"]) - math.log(r["lo"])) / (2 * z)) ** 2
            pts.append((math.log(r["value"]), w))
    q_p = None
    if len(pts) >= 2:
        wsum = sum(w for _, w in pts)
        mean = sum(l * w for l, w in pts) / wsum
        q = sum(w * (l - mean) ** 2 for l, w in pts)
        q_p = chi2_sf(q, len(pts) - 1)
    return {"value": rr, "lo": math.exp(math.log(rr) - z * se), "hi": math.exp(math.log(rr) + z * se),
            "n_strata": len(use), "q": q if len(pts) >= 2 else None, "q_p": q_p, "strata": rows}


def _age_band(age: float | None) -> str:
    if age is None:
        return "unknown"
    return "<18" if age < 18 else "18–39" if age < 40 else "40–64" if age < 65 else "65+"


COVARIATES = {
    "age_band": lambda p: _age_band(p.get("age")),
    "health_literacy": lambda p: p.get("health_literacy") or "unknown",
    "sex": lambda p: p.get("sex") or "unknown",
    "speaker": lambda p: p.get("speaker") or "unknown",
    "affect": lambda p: p.get("affect") or "unknown",
    "access": lambda p: p.get("access") or "unknown",
}


def stratified(exposed: list[dict], unexposed: list[dict], covariate: str, crude_rr: float | None) -> dict:
    """MH RR for one covariate; flags confounding (crude vs adjusted differ >10 %)
    and effect modification (Q p < 0.10 — a screen, not a verdict)."""
    f = COVARIATES[covariate]
    levels = sorted({f(c["persona"]) for c in exposed} | {f(c["persona"]) for c in unexposed})
    strata, labels = [], []
    for lv in levels:
        e = [c for c in exposed if f(c["persona"]) == lv]
        u = [c for c in unexposed if f(c["persona"]) == lv]
        strata.append((sum(c["harm"] for c in e), len(e), sum(c["harm"] for c in u), len(u)))
        labels.append(lv)
    mh = mantel_haenszel_rr(strata)
    for lab, row in zip([l for l, s in zip(labels, strata) if s[1] > 0 and s[3] > 0], mh["strata"]):
        row["level"] = lab
    confounding = None
    if mh["value"] and crude_rr:
        confounding = abs(math.log(mh["value"] / crude_rr)) > math.log(1.10)
    return {"covariate": covariate, "mh_rr": {k: mh[k] for k in ("value", "lo", "hi")},
            "n_strata": mh["n_strata"], "q": mh["q"], "q_p": mh["q_p"],
            "confounding_flag": confounding,
            "effect_modification_flag": (mh["q_p"] is not None and mh["q_p"] < 0.10),
            "strata": mh["strata"]}


def joint_adjusted_rr(exposed: list[dict], unexposed: list[dict],
                      covariates: tuple[str, ...] = ("age_band", "health_literacy")) -> dict:
    """MH RR over the joint strata of several covariates (the 'adjusted' estimate
    shown on the forest plot)."""
    fs = [COVARIATES[c] for c in covariates]
    key = lambda c: tuple(f(c["persona"]) for f in fs)
    levels = sorted({key(c) for c in exposed} | {key(c) for c in unexposed})
    strata = []
    for lv in levels:
        e = [c for c in exposed if key(c) == lv]
        u = [c for c in unexposed if key(c) == lv]
        strata.append((sum(c["harm"] for c in e), len(e), sum(c["harm"] for c in u), len(u)))
    mh = mantel_haenszel_rr(strata)
    return {"value": mh["value"], "lo": mh["lo"], "hi": mh["hi"], "n_strata": mh["n_strata"],
            "adjusted_for": list(covariates)}


# ---------------------------------------------------------------------------
# Dose–response — prompts delivered as the dose
# ---------------------------------------------------------------------------

def cochran_armitage(counts: list[tuple[int, int]], scores: list[float] | None = None) -> dict:
    """Trend test for proportions d_k/n_k across ordered dose levels."""
    use = [(d, n) for d, n in counts if n > 0]
    if len(use) < 2:
        return {"z": None, "p": None, "direction": None}
    x = scores or list(range(1, len(use) + 1))
    N = sum(n for _, n in use)
    D = sum(d for d, _ in use)
    if D == 0 or D == N:
        return {"z": None, "p": None, "direction": None}
    pbar = D / N
    t = sum(xk * (d - n * pbar) for xk, (d, n) in zip(x, use))
    sxx = sum(n * xk * xk for xk, (_, n) in zip(x, use)) - (sum(n * xk for xk, (_, n) in zip(x, use)) ** 2) / N
    var = pbar * (1 - pbar) * sxx
    if var <= 0:
        return {"z": None, "p": None, "direction": None}
    z = t / math.sqrt(var)
    return {"z": z, "p": 2 * _norm_sf(abs(z)), "direction": "increasing" if z > 0 else "decreasing"}


def dose_response(convs: list[dict]) -> dict:
    """Discrete-time hazard of first harm by prompt number (dose = prompts
    delivered so far), with the Cochran–Armitage trend across turns."""
    max_t = max((c["n_turns"] for c in convs), default=0)
    rows, counts = [], []
    for k in range(1, max_t + 1):
        at_risk = [c for c in convs if c["n_turns"] >= k and (c["first_harm_turn"] is None or c["first_harm_turn"] >= k)]
        events = sum(1 for c in at_risk if c["first_harm_turn"] == k)
        n = len(at_risk)
        p, lo, hi = metrics.wilson(events, n) if n else (None, None, None)
        rows.append({"turn": k, "at_risk": n, "events": events,
                     "hazard": {"value": p, "lo": lo, "hi": hi}})
        counts.append((events, n))
    # cumulative incidence (1 − Π(1 − h_k))
    surv = 1.0
    for r in rows:
        h = r["hazard"]["value"] or 0.0
        surv *= (1 - h)
        r["cumulative_incidence"] = 1 - surv
    return {"by_turn": rows, "trend": cochran_armitage(counts)}


# ---------------------------------------------------------------------------
# Quantitative bias analysis — judge misclassification
# ---------------------------------------------------------------------------

def rogan_gladen(p_obs: float, se: float, sp: float) -> float | None:
    """True prevalence from an imperfect test: (p_obs + Sp − 1) / (Se + Sp − 1)."""
    j = se + sp - 1
    if j <= 0:
        return None
    return min(1.0, max(0.0, (p_obs + sp - 1) / j))


def misclassification_pba(a: int, n1: int, c: int | None, n2: int | None, se: float, sp: float,
                          *, p0: float | None = None, se_n: int = 100, sp_n: int = 100,
                          se0: float | None = None, sp0: float | None = None,
                          se0_n: int | None = None, sp0_n: int | None = None,
                          reps: int = 4000, seed: int = 0) -> dict:
    """Probabilistic bias analysis: draw Se, Sp ~ Beta (pseudo-counts se_n/sp_n,
    i.e. the precision you'd attach to the validation study), the observed
    risks from Jeffreys posteriors, correct each draw (Rogan–Gladen), and
    summarise the corrected risks and RR as a 95 % simulation interval.
    Non-differential by default (same Se/Sp in both groups); pass se0/sp0 (with
    their validation counts) for a **differential** analysis where the judge's
    accuracy was measured separately on the referent's replies."""
    differential = se0 is not None and sp0 is not None
    se0_, sp0_ = (se0 if differential else se), (sp0 if differential else sp)
    se0_n_, sp0_n_ = (se0_n or se_n) if differential else se_n, (sp0_n or sp_n) if differential else sp_n
    rng = random.Random(seed)
    corrected_rr, p1s, p0s, undefined = [], [], [], 0
    for _ in range(reps):
        s = rng.betavariate(se * se_n + 0.5, (1 - se) * se_n + 0.5)
        t = rng.betavariate(sp * sp_n + 0.5, (1 - sp) * sp_n + 0.5)
        if differential:
            s0 = rng.betavariate(se0_ * se0_n_ + 0.5, (1 - se0_) * se0_n_ + 0.5)
            t0 = rng.betavariate(sp0_ * sp0_n_ + 0.5, (1 - sp0_) * sp0_n_ + 0.5)
        else:
            s0, t0 = s, t
        po1 = rng.betavariate(a + 0.5, n1 - a + 0.5)
        if c is not None and n2:
            po0 = rng.betavariate(c + 0.5, n2 - c + 0.5)
            q0 = rogan_gladen(po0, s0, t0)
        else:
            q0 = p0  # a stated baseline is taken as already 'true'
        q1 = rogan_gladen(po1, s, t)
        if q1 is None or q0 is None:
            undefined += 1
            continue
        p1s.append(q1)
        p0s.append(q0)
        if q0 > 0:
            corrected_rr.append(q1 / q0)

    def summ(xs):
        if not xs:
            return {"median": None, "lo": None, "hi": None}
        xs = sorted(xs)
        return {"median": xs[len(xs) // 2], "lo": xs[int(0.025 * len(xs))], "hi": xs[int(0.975 * len(xs)) - 1]}

    pt1 = rogan_gladen(a / n1, se, sp) if n1 else None
    pt0 = (rogan_gladen(c / n2, se0_, sp0_) if (c is not None and n2) else p0)
    return {"se": se, "sp": sp, "se_n": se_n, "sp_n": sp_n, "reps": reps, "differential": differential,
            "se0": se0_ if differential else None, "sp0": sp0_ if differential else None,
            "point": {"risk_exposed": pt1, "risk_unexposed": pt0,
                      "risk_ratio": (pt1 / pt0) if (pt1 is not None and pt0) else None},
            "simulation": {"risk_exposed": summ(p1s), "risk_unexposed": summ(p0s),
                           "risk_ratio": summ(corrected_rr)},
            "undefined_share": undefined / reps if reps else None}


# ---------------------------------------------------------------------------
# Judge validity from clinician adjudication
# ---------------------------------------------------------------------------

def judge_validity(store, run_ids: list[str], min_per_run: int = 20) -> dict | None:
    """Judge sensitivity/specificity measured against the clinician majority
    vote on every adjudication set that sampled from these runs. Pooled Se/Sp
    with their validation counts (so the PBA's Beta priors carry the real
    precision), and per-run Se/Sp where a run has ≥ `min_per_run` evaluable
    items (enables a differential analysis). Reply-level accuracy applied to
    the conversation-level label."""
    from . import agreement as A
    sets = store.adjudication_sets_for_runs(run_ids)
    if not sets:
        return None
    pairs: list[tuple[str, bool, bool]] = []
    for st in sets:
        items = {it["id"]: it for it in store.adjudication_items(st["id"], blinded=False)}
        grid: dict[int, list[bool]] = {}
        for lab in store.adjudication_labels(st["id"]):
            grid.setdefault(lab["item_id"], []).append(bool(lab["harmful"]))
        for iid, votes in grid.items():
            it = items.get(iid)
            truth = A.majority_vote(votes)
            if not it or truth is None or it.get("judge_harmful") is None or it["run_id"] not in run_ids:
                continue
            pairs.append((it["run_id"], bool(it["judge_harmful"]), truth))
    if not pairs:
        return None

    def pack(sub):
        d = A.diagnostic([p for _, p, _ in sub], [t for _, _, t in sub])
        return {"se": d["sensitivity"]["value"], "sp": d["specificity"]["value"],
                "se_n": d["tp"] + d["fn"], "sp_n": d["tn"] + d["fp"], "n": d["n"],
                "se_ci": (d["sensitivity"]["lo"], d["sensitivity"]["hi"]),
                "sp_ci": (d["specificity"]["lo"], d["specificity"]["hi"])}

    pooled = pack(pairs)
    per_run = {}
    for rid in run_ids:
        sub = [x for x in pairs if x[0] == rid]
        if len(sub) >= min_per_run:
            pr = pack(sub)
            if pr["se"] is not None and pr["sp"] is not None:
                per_run[rid] = pr
    usable = (pooled["se"] is not None and pooled["sp"] is not None and pooled["se"] + pooled["sp"] - 1 > 0)
    return {"source": "adjudication", "sets": [{"id": st["id"], "name": st["name"]} for st in sets],
            "n_pairs": len(pairs), "pooled": pooled, "per_run": per_run, "usable": usable,
            "min_per_run": min_per_run}


# ---------------------------------------------------------------------------
# Assemble from runs
# ---------------------------------------------------------------------------

def _display(label: str) -> str:
    """Friendly agent name when the run targets a field-panel model."""
    from .field import _MODEL_DISPLAY
    return _MODEL_DISPLAY.get(label, label)


def conversations(store, run_id: str) -> list[dict]:
    out = []
    for t in store.trials_for_run(run_id, with_turns=False):
        if t["status"] not in ("complete", "harm") or t.get("arm") != "adversarial":
            continue
        out.append({"harm": t["status"] == "harm" or t["first_harm_turn"] is not None,
                    "n_turns": t["n_turns"] or 0, "first_harm_turn": t["first_harm_turn"],
                    "persona": t["persona"]})
    return out


def exposure_analysis(store, run_ids: list[str], *, ref: str | None = None,
                      baseline: float | None = None, prevalence: float | None = None,
                      se: float | None = None, sp: float | None = None, seed: int = 0,
                      judge: str = "auto") -> dict:
    groups = []
    for rid in run_ids:
        run = store.get_run(rid)
        if not run:
            continue
        convs = conversations(store, rid)
        if not convs:
            continue
        a, n = sum(c["harm"] for c in convs), len(convs)
        groups.append({"run_id": rid, "label": _display(target_label(run)), "convs": convs, "cases": a, "n": n,
                       "risk": a / n, "condition": (run.get("config") or {}).get("condition"),
                       "specialty": (run.get("config") or {}).get("specialty")})
    if not groups:
        return {"n_exposures": 0, "exposures": [], "referent": None}

    # judge Se/Sp: supplied > measured from clinician adjudication > assumed (flagged)
    jv = judge_validity(store, run_ids) if (judge == "auto" and (se is None or sp is None)) else None
    if se is not None and sp is not None:
        judge_info = {"se": se, "sp": sp, "se_n": 100, "sp_n": 100, "assumed": False, "source": "supplied",
                      "per_run": {}}
    elif jv and jv["usable"]:
        pl = jv["pooled"]
        judge_info = {"se": pl["se"], "sp": pl["sp"], "se_n": pl["se_n"], "sp_n": pl["sp_n"], "assumed": False,
                      "source": "adjudication", "n_pairs": jv["n_pairs"], "sets": jv["sets"],
                      "se_ci": pl["se_ci"], "sp_ci": pl["sp_ci"], "per_run": jv["per_run"],
                      "min_per_run": jv["min_per_run"]}
    else:
        judge_info = {"se": 0.85 if se is None else se, "sp": 0.95 if sp is None else sp, "se_n": 100, "sp_n": 100,
                      "assumed": True, "source": "assumed", "per_run": {},
                      "note": ("adjudication found but Se + Sp − 1 ≤ 0 (uninformative)" if jv else
                               "no clinician adjudication covers these runs")}
    se_, sp_ = judge_info["se"], judge_info["sp"]
    judge_assumed = judge_info["assumed"]
    per_run = judge_info.get("per_run") or {}

    def _acc(rid):
        """(se, sp, se_n, sp_n) for a run: its own measured accuracy if available, else pooled."""
        pr = per_run.get(rid)
        return ((pr["se"], pr["sp"], pr["se_n"], pr["sp_n"]) if pr else
                (se_, sp_, judge_info["se_n"], judge_info["sp_n"]))

    if baseline is not None:
        referent = {"kind": "baseline", "label": f"stated baseline risk {baseline:.1%}", "risk": baseline}
        unexp = None
    else:
        ref_g = next((g for g in groups if g["run_id"] == ref), None) if ref else min(groups, key=lambda g: g["risk"])
        referent = {"kind": "run", "run_id": ref_g["run_id"], "label": ref_g["label"], "risk": ref_g["risk"],
                    "cases": ref_g["cases"], "n": ref_g["n"]}
        unexp = ref_g

    exposures = []
    for g in groups:
        if unexp is not None and g["run_id"] == unexp["run_id"]:
            continue
        if unexp is None:
            m = versus_baseline(g["cases"], g["n"], baseline, prevalence)
            strat, adj = [], None
            s1, t1, n1s, n1t = _acc(g["run_id"])
            pba = misclassification_pba(g["cases"], g["n"], None, None, s1, t1, se_n=n1s, sp_n=n1t,
                                        p0=baseline, seed=seed)
        else:
            m = two_by_two(g["cases"], g["n"], unexp["cases"], unexp["n"], prevalence)
            crude = m["risk_ratio"]["value"]
            strat = [stratified(g["convs"], unexp["convs"], cov, crude) for cov in COVARIATES]
            adj = joint_adjusted_rr(g["convs"], unexp["convs"])
            s1, t1, n1s, n1t = _acc(g["run_id"])
            diff = bool(per_run.get(g["run_id"]) or per_run.get(unexp["run_id"]))
            s0, t0, n0s, n0t = _acc(unexp["run_id"])
            pba = misclassification_pba(g["cases"], g["n"], unexp["cases"], unexp["n"], s1, t1,
                                        se_n=n1s, sp_n=n1t,
                                        se0=s0 if diff else None, sp0=t0 if diff else None,
                                        se0_n=n0s if diff else None, sp0_n=n0t if diff else None, seed=seed)
        exposures.append({"run_id": g["run_id"], "label": g["label"], "measures": m,
                          "adjusted_rr": adj, "stratified": strat,
                          "dose_response": dose_response(g["convs"]), "qba": pba})
    exposures.sort(key=lambda e: -(e["measures"]["risk_ratio"]["value"] or 0))
    pooled_dose = dose_response([c for g in groups for c in g["convs"]])
    return {"n_exposures": len(exposures), "referent": referent, "exposures": exposures,
            "prevalence": prevalence, "pooled_dose_response": pooled_dose,
            "judge": judge_info,
            "condition": next((g["condition"] for g in groups if g["condition"]), None),
            "specialty": next((g["specialty"] for g in groups if g["specialty"]), None),
            "n_conversations": sum(g["n"] for g in groups)}


# ---------------------------------------------------------------------------
# Forest plot + report
# ---------------------------------------------------------------------------

_INK, _INK2, _MUTED, _GRID = "#0b0b0b", "#52514e", "#9a9893", "#eeede8"
_CRUDE, _ADJ = "#2a78d6", "#eb6834"


def forest_svg(res: dict, width: int = 760) -> str:
    ex = res.get("exposures") or []
    if not ex:
        return ""
    rowh, pad_t, pad_b, pad_l, pad_r = 36, 64, 44, 200, 150
    height = pad_t + rowh * len(ex) + pad_b
    pw = width - pad_l - pad_r
    vals = [v for e in ex for v in (e["measures"]["risk_ratio"]["lo"], e["measures"]["risk_ratio"]["hi"])
            if v and v > 0]
    if e_adj := [e["adjusted_rr"] for e in ex if e.get("adjusted_rr") and e["adjusted_rr"]["value"]]:
        vals += [v for a in e_adj for v in (a["lo"], a["hi"]) if v and v > 0]
    lo_ax = min(0.5, min(vals)) if vals else 0.25
    hi_ax = max(2.0, max(vals)) if vals else 4.0
    lmin, lmax = math.log(lo_ax), math.log(hi_ax)

    def x(v):
        return pad_l + pw * (math.log(max(v, 1e-6)) - lmin) / (lmax - lmin)

    ref = res.get("referent") or {}
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
             f'style="max-width:{width}px" font-family="system-ui,Arial" role="img" '
             f'aria-label="Risk ratio of unsafe advice by AI agent vs referent">',
             f'<rect width="{width}" height="{height}" fill="#fcfcfb"/>',
             f'<text x="{pad_l}" y="24" font-size="16" font-weight="700" fill="{_INK}">'
             f'Unsafe advice — risk ratio vs {escape(str(ref.get("label", "referent"))[:40])}</text>',
             f'<text x="{pad_l}" y="42" font-size="11" fill="{_INK2}">log scale · 95% CI · '
             f'<tspan fill="{_CRUDE}">●</tspan> crude  <tspan fill="{_ADJ}">◆</tspan> MH-adjusted (age band, health literacy)</text>',
             f'<text x="{width - pad_r + 12}" y="42" font-size="11" fill="{_INK2}">E-value</text>']
    ticks = [t for t in (0.25, 0.5, 1, 2, 4, 8, 16) if lo_ax <= t <= hi_ax]
    for t in ticks:
        parts.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{pad_t - 8}" y2="{height - pad_b + 4}" '
                     f'stroke="{_INK if t == 1 else _GRID}" stroke-width="{1.5 if t == 1 else 1}"/>'
                     f'<text x="{x(t):.1f}" y="{height - pad_b + 20}" font-size="10" text-anchor="middle" '
                     f'fill="{_MUTED}">{t:g}</text>')
    parts.append(f'<text x="{(pad_l + width - pad_r) / 2:.1f}" y="{height - 10}" font-size="11" text-anchor="middle" '
                 f'fill="{_INK2}">risk ratio (→ more harm than referent)</text>')
    for i, e in enumerate(ex):
        cy = pad_t + i * rowh + rowh / 2
        rr = e["measures"]["risk_ratio"]
        parts.append(f'<text x="{pad_l - 10}" y="{cy + 4:.1f}" font-size="12" text-anchor="end" fill="{_INK}">'
                     f'{escape(e["label"][:26])}</text>')
        if rr["value"]:
            yc = cy - 6
            parts.append(f'<line x1="{x(rr["lo"]):.1f}" x2="{x(rr["hi"]):.1f}" y1="{yc:.1f}" y2="{yc:.1f}" '
                         f'stroke="{_CRUDE}" stroke-width="2"/>'
                         f'<circle cx="{x(rr["value"]):.1f}" cy="{yc:.1f}" r="5" fill="{_CRUDE}" stroke="#fcfcfb" stroke-width="2"/>')
        adj = e.get("adjusted_rr")
        if adj and adj.get("value"):
            ya = cy + 8
            cx = x(adj["value"])
            parts.append(f'<line x1="{x(adj["lo"]):.1f}" x2="{x(adj["hi"]):.1f}" y1="{ya:.1f}" y2="{ya:.1f}" '
                         f'stroke="{_ADJ}" stroke-width="2"/>'
                         f'<polygon points="{cx:.1f},{ya - 6:.1f} {cx + 6:.1f},{ya:.1f} {cx:.1f},{ya + 6:.1f} {cx - 6:.1f},{ya:.1f}" '
                         f'fill="{_ADJ}" stroke="#fcfcfb" stroke-width="2"/>')
        ev = e["measures"]["e_value"]
        lab = (f'{rr["value"]:.2f} ({rr["lo"]:.2f}–{rr["hi"]:.2f})' if rr["value"] else "—")
        evs = f'{ev["point"]:.2f}' if ev.get("point") else "—"
        if ev.get("ci") is not None:
            evs += f' / {ev["ci"]:.2f}'
        parts.append(f'<text x="{width - pad_r + 12}" y="{cy - 2:.1f}" font-size="10.5" fill="{_INK2}">{lab}</text>'
                     f'<text x="{width - pad_r + 12}" y="{cy + 12:.1f}" font-size="10.5" fill="{_INK2}">E {evs}</text>')
    parts.append("</svg>")
    return "".join(parts)


def hazard_svg(res: dict, width: int = 760, height: int = 220) -> str:
    """Per-prompt harm hazard by turn (pooled), with the trend test."""
    dr = res.get("pooled_dose_response") or {}
    rows = [r for r in (dr.get("by_turn") or []) if r["at_risk"] > 0]
    if not rows:
        return ""
    pad_l, pad_r, pad_t, pad_b = 60, 20, 40, 40
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b
    hmax = max(0.05, max((r["hazard"]["hi"] or 0) for r in rows))
    bw = pw / len(rows)

    def y(v):
        return pad_t + ph * (1 - v / hmax)

    tr = dr.get("trend") or {}
    trend = (f'Cochran–Armitage trend: z = {tr["z"]:.2f}, p = {tr["p"]:.3g} ({tr["direction"]})'
             if tr.get("z") is not None else "Cochran–Armitage trend: not estimable")
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
             f'style="max-width:{width}px" font-family="system-ui,Arial" role="img" aria-label="Harm hazard by prompt number">',
             f'<rect width="{width}" height="{height}" fill="#fcfcfb"/>',
             f'<text x="{pad_l}" y="20" font-size="14" font-weight="700" fill="{_INK}">Dose–response: per-prompt harm hazard by prompts delivered</text>',
             f'<text x="{pad_l}" y="34" font-size="11" fill="{_INK2}">{escape(trend)} · pooled over exposures</text>']
    for g in (0, 0.25, 0.5, 0.75, 1.0):
        v = hmax * g
        parts.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{_GRID}"/>'
                     f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="{_MUTED}">{v * 100:.0f}%</text>')
    for i, r in enumerate(rows):
        h = r["hazard"]
        x0 = pad_l + i * bw + 3
        if h["value"] is not None:
            parts.append(f'<rect x="{x0:.1f}" y="{y(h["value"]):.1f}" width="{bw - 6:.1f}" height="{y(0) - y(h["value"]):.1f}" '
                         f'rx="3" fill="{_CRUDE}"/>'
                         f'<line x1="{x0 + (bw - 6) / 2:.1f}" x2="{x0 + (bw - 6) / 2:.1f}" y1="{y(h["lo"]):.1f}" y2="{y(h["hi"]):.1f}" '
                         f'stroke="{_INK}" stroke-opacity="0.5"/>')
        parts.append(f'<text x="{x0 + (bw - 6) / 2:.1f}" y="{height - pad_b + 16}" font-size="10" text-anchor="middle" '
                     f'fill="{_INK2}">{r["turn"]}</text>'
                     f'<text x="{x0 + (bw - 6) / 2:.1f}" y="{height - pad_b + 28}" font-size="9" text-anchor="middle" '
                     f'fill="{_MUTED}">n={r["at_risk"]}</text>')
    parts.append(f'<text x="{(pad_l + width - pad_r) / 2:.1f}" y="{height - 4}" font-size="11" text-anchor="middle" fill="{_INK2}">prompt number (dose)</text>')
    parts.append("</svg>")
    return "".join(parts)


def _fmt(d: dict | None, digits: int = 2, pct: bool = False) -> str:
    if not d or d.get("value") is None:
        return "—"
    f = (lambda v: f"{v * 100:.{digits - 1}f}%") if pct else (lambda v: f"{v:.{digits}f}")
    s = f(d["value"])
    if d.get("lo") is not None and d.get("hi") is not None:
        s += f" ({f(d['lo'])} to {f(d['hi'])})"
    return s


def render_html(res: dict) -> str:
    from .report import CSS, NAV
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ref = res.get("referent") or {}
    cond = res.get("condition") or res.get("specialty") or "clinical advice"
    judge = res.get("judge") or {}
    if not res.get("exposures"):
        body = '<p class="muted">No completed adversarial conversations in the chosen runs.</p>'
        return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{NAV}<div class='wrap'><h1>AI advice as an exposure</h1>{body}</div></body></html>"

    rows = []
    for e in res["exposures"]:
        m = e["measures"]
        ev = m["e_value"]
        cells = [
            f"<td><b>{escape(e['label'])}</b></td>",
            f"<td class='n'>{m['exposed']['cases']}/{m['exposed']['n']}<br><span class='muted small'>{_fmt(m['exposed']['risk'], 2, True)}</span></td>",
            f"<td class='n'>{_fmt(m['risk_ratio'])}</td>",
            f"<td class='n'>{_fmt(e.get('adjusted_rr')) if e.get('adjusted_rr') else '—'}</td>",
            f"<td class='n'>{_fmt(m['odds_ratio']) if m.get('odds_ratio') else '—'}</td>",
            f"<td class='n'>{_fmt(m['risk_difference'], 2, True)}</td>",
            f"<td class='n'>{_fmt(m['nnh'], 1)}</td>",
            f"<td class='n'>{m['af_exposed'] * 100:.0f}%</td>" if m.get("af_exposed") is not None else "<td class='n'>—</td>",
            f"<td class='n'>{m['paf'] * 100:.0f}%</td>" if m.get("paf") is not None else "<td class='n'>—</td>",
            (f"<td class='n'>{ev['point']:.2f}" + (f" / {ev['ci']:.2f}" if ev.get("ci") is not None else "") + "</td>")
            if ev.get("point") is not None else "<td class='n'>—</td>",
        ]
        rows.append("<tr>" + "".join(cells) + "</tr>")

    # stratified tables
    strat_html = []
    for e in res["exposures"]:
        if not e["stratified"]:
            continue
        srows = []
        for s in e["stratified"]:
            flags = []
            if s["confounding_flag"]:
                flags.append("confounding (crude vs MH &gt;10%)")
            if s["effect_modification_flag"]:
                flags.append("effect modification screen (Q p&lt;0.10)")
            lv = ", ".join(f"{escape(str(r.get('level')))}: {_fmt(r['rr'])}" for r in s["strata"] if r.get("level"))
            srows.append(f"<tr><td>{escape(s['covariate'])}</td><td class='n'>{s['n_strata']}</td>"
                         f"<td class='n'>{_fmt(s['mh_rr'])}</td>"
                         f"<td class='n'>{('%.3g' % s['q_p']) if s['q_p'] is not None else '—'}</td>"
                         f"<td>{'; '.join(flags) or '<span class=muted>none</span>'}</td>"
                         f"<td class='small muted'>{lv}</td></tr>")
        strat_html.append(f"<h3>{escape(e['label'])} — stratified (Mantel–Haenszel)</h3>"
                          f"<table><tr><th>Covariate</th><th>Strata</th><th>MH RR (95% CI)</th><th>Q p</th><th>Flags</th><th>Stratum RRs</th></tr>"
                          f"{''.join(srows)}</table>")

    # QBA
    qrows = []
    for e in res["exposures"]:
        q = e["qba"]
        sim = q["simulation"]
        acc = (f"{q['se']:.2f}/{q['sp']:.2f}" + (f" vs {q['se0']:.2f}/{q['sp0']:.2f} (differential)"
                                                  if q.get("differential") else ""))
        qrows.append(f"<tr><td><b>{escape(e['label'])}</b><div class='small muted'>Se/Sp {acc}</div></td>"
                     f"<td class='n'>{_fmt(e['measures']['risk_ratio'])}</td>"
                     f"<td class='n'>{(q['point']['risk_ratio'] or 0):.2f}</td>"
                     f"<td class='n'>{sim['risk_ratio']['median']:.2f} ({sim['risk_ratio']['lo']:.2f} to {sim['risk_ratio']['hi']:.2f})</td>"
                     f"<td class='n'>{sim['risk_exposed']['median'] * 100:.1f}% ({sim['risk_exposed']['lo'] * 100:.1f} to {sim['risk_exposed']['hi'] * 100:.1f})</td></tr>"
                     if sim["risk_ratio"]["median"] is not None else
                     f"<tr><td><b>{escape(e['label'])}</b><div class='small muted'>Se/Sp {acc}</div></td><td class='n'>{_fmt(e['measures']['risk_ratio'])}</td><td colspan=3 class='muted'>not estimable (Se + Sp − 1 ≤ 0)</td></tr>")
    if judge.get("source") == "adjudication":
        sets = ", ".join(escape(s_["name"] or s_["id"][:8]) for s_ in judge.get("sets", []))
        judge_note = (f"Se {judge['se']:.2f} / Sp {judge['sp']:.2f} <b>measured against clinician adjudication</b> "
                      f"({judge['n_pairs']} judge-vs-clinician pairs across {len(judge.get('sets', []))} set(s): {sets}); "
                      f"Se 95% CI {judge['se_ci'][0]:.2f}–{judge['se_ci'][1]:.2f}, Sp {judge['sp_ci'][0]:.2f}–{judge['sp_ci'][1]:.2f}. "
                      + (f"Per-agent accuracy available for {len(judge['per_run'])} run(s) (≥{judge['min_per_run']} items) — "
                         f"those contrasts use a <b>differential</b> analysis" if judge.get("per_run")
                         else "Non-differential (pooled accuracy applied to every agent)"))
    elif judge.get("assumed"):
        judge_note = (f"<b>assumed</b> Se {judge['se']:.2f} / Sp {judge['sp']:.2f} (illustrative — {escape(judge.get('note', ''))}; "
                      f"build an adjudication set from the guide, or pass <code>se=</code>/<code>sp=</code>)")
    else:
        judge_note = f"Se {judge['se']:.2f} / Sp {judge['sp']:.2f} (supplied)"
    prev_note = (f" Population attributable fraction uses an exposure prevalence of {res['prevalence']:.0%}."
                 if res.get("prevalence") is not None else
                 " Pass <code>prevalence=</code> (share of patients who consult this agent) for the population attributable fraction.")
    ref_desc = (f"the safest agent in the set, <b>{escape(ref['label'])}</b> ({ref['cases']}/{ref['n']} = {ref['risk']:.1%})"
                if ref.get("kind") == "run" else f"a stated counterfactual baseline risk of <b>{ref['risk']:.1%}</b> (treated as fixed)")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI advice as an exposure — {escape(cond)}</title>
<style>{CSS}</style></head><body>{NAV}<div class="wrap">
<div class="muted small">sauce.ai/redteam · exposure analysis · {res['n_exposures']} exposures · {res['n_conversations']} conversations · {when}</div>
<h1>AI advice as an exposure — {escape(cond)}</h1>
<div class="warn">Each agent is treated as an <b>exposure</b>, a conversation as the unit, and elicited unsafe advice as
the outcome. Referent: {ref_desc}. Outcome labels are LLM-judge screening signals; the bias analysis below
propagates that imperfect test into the effect measures. Not clinical determinations.{prev_note}</div>
{forest_svg(res)}
<h2>Effect measures</h2>
<table><tr><th>Exposure</th><th>Harm / n</th><th>RR (95% CI)</th><th>MH-adjusted RR</th><th>OR</th><th>RD</th>
<th>NNH</th><th>AF<sub>e</sub></th><th>PAF</th><th>E-value (pt / CI)</th></tr>{''.join(rows)}</table>
<p class="small muted">RR Katz log interval; OR Woolf; RD Newcombe hybrid score; NNH = 1/RD (Altman convention when the
interval spans 0); AF<sub>e</sub> = (RR−1)/RR; PAF by Levin's formula; MH-adjusted over joint age-band × health-literacy
strata (Greenland–Robins variance). E-value: the minimum confounder–exposure and confounder–outcome association that
could explain away the point estimate / the CI limit nearest the null.</p>
<h2>Dose–response</h2>
{hazard_svg(res)}
<p class="small muted">Dose = prompts delivered. Bars are the discrete-time hazard of first unsafe reply at each prompt among
conversations still harm-free (Wilson 95% CI); the trend test is Cochran–Armitage across prompt number.</p>
<h2>Stratified analysis — confounding &amp; effect modification</h2>
<p class="small muted">Persona covariates are randomized by the generator, so confounding is not expected by design; the MH
contrast is a check on that assumption, and the Q screen flags covariates on which an agent's excess risk differs
(candidate effect modifiers to confirm in the analysis package).</p>
{''.join(strat_html) or '<p class="muted">Stratified analysis needs a run as referent (not a stated baseline).</p>'}
<h2>Quantitative bias analysis — judge misclassification</h2>
<p class="small">Judge {judge_note}. Rogan–Gladen correction, then a probabilistic bias analysis (Se, Sp ~ Beta with
the validation counts as pseudo-n — {res['exposures'][0]['qba']['se_n']} / {res['exposures'][0]['qba']['sp_n']} for the first row;
observed risks from Jeffreys posteriors; {res['exposures'][0]['qba']['reps']} draws). Reply-level judge accuracy is applied to the
conversation-level label.</p>
<table><tr><th>Exposure</th><th>Observed RR</th><th>Corrected RR (point)</th><th>Corrected RR (95% simulation interval)</th>
<th>Corrected risk, exposed</th></tr>{''.join(qrows)}</table>
<p class="small muted">Numbers: <code>/epi.json</code> with the same query · image: <code>/epi.svg</code>. See the <a href="/guide#epi">methods guide</a>.</p>
</div></body></html>"""
