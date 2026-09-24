"""Sample-size and power for the CHE study (RESEARCH.md §4).

Pure stdlib. Covers the designs the protocol actually uses:

- **Precision** on a single proportion (a target CHR with a chosen 95% CI
  half-width) — the usual planning target when the comparison is descriptive.
- **Two-proportion** comparisons (adversarial vs control, or model A vs B):
  required n per group, achieved power, and the minimum detectable difference.
- A **design effect** for clustering (turns within conversations) so the plan
  is not anticonservative.
- The **two-phase review burden** (how many outputs clinicians must actually
  label) given the screener positivity rate and the negative sampling rate.
- **Rule-of-three** planning for the rare/zero-event regime.

All two-sided unless noted.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Normal CDF and its inverse (Acklam's algorithm) — no scipy.
# ---------------------------------------------------------------------------

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile). Acklam, |error| < 1.15e-9."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# ---------------------------------------------------------------------------
# Design effect (clustering)
# ---------------------------------------------------------------------------

def design_effect(cluster_size: float, icc: float) -> float:
    """DE = 1 + (m - 1)·ICC for equal clusters of size m (turns per conversation)."""
    return 1.0 + (max(1.0, cluster_size) - 1.0) * max(0.0, icc)


# ---------------------------------------------------------------------------
# Single-proportion precision (CI half-width)
# ---------------------------------------------------------------------------

def n_for_precision(p: float, half_width: float, conf: float = 0.95,
                    design_effect: float = 1.0) -> dict:
    """Attempts needed to estimate a proportion p to a given 95%-CI half-width
    (normal approximation), inflated by the design effect."""
    z = norm_ppf(1 - (1 - conf) / 2)
    n = (z * z * p * (1 - p)) / (half_width * half_width) * design_effect
    return {"n": math.ceil(n), "p": p, "half_width": half_width, "conf": conf,
            "design_effect": design_effect, "z": z}


# ---------------------------------------------------------------------------
# Two-proportion comparison
# ---------------------------------------------------------------------------

def n_two_proportions(p1: float, p2: float, alpha: float = 0.05, power: float = 0.80,
                      ratio: float = 1.0, design_effect: float = 1.0) -> dict:
    """Per-group n to detect p1 vs p2 (two-sided), normal approximation with an
    unequal-allocation `ratio` = n2/n1. Returns n1, n2 inflated by DE."""
    if p1 == p2:
        raise ValueError("p1 and p2 must differ")
    za = norm_ppf(1 - alpha / 2)
    zb = norm_ppf(power)
    k = ratio
    pbar = (p1 + k * p2) / (1 + k)
    qbar = 1 - pbar
    num = (za * math.sqrt((1 + 1 / k) * pbar * qbar)
           + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / k)) ** 2
    n1 = num / (p1 - p2) ** 2 * design_effect
    n1 = math.ceil(n1)
    n2 = math.ceil(n1 * k)
    return {"n1": n1, "n2": n2, "total": n1 + n2, "p1": p1, "p2": p2,
            "alpha": alpha, "power": power, "ratio": ratio, "design_effect": design_effect}


def power_two_proportions(p1: float, p2: float, n1: int, n2: int, alpha: float = 0.05) -> dict:
    """Achieved power for detecting p1 vs p2 with n1, n2 (two-sided, unpooled)."""
    za = norm_ppf(1 - alpha / 2)
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    if se == 0:
        return {"power": None}
    z = abs(p1 - p2) / se - za
    return {"power": norm_cdf(z), "p1": p1, "p2": p2, "n1": n1, "n2": n2, "alpha": alpha}


def min_detectable_difference(p_ref: float, n_per_group: int, alpha: float = 0.05,
                              power: float = 0.80, design_effect: float = 1.0) -> dict:
    """Smallest |p2 - p_ref| detectable with n per group at the target power
    (search over p2 on both sides; returns the smaller absolute effect)."""
    def ok(p2):
        eff_n = n_per_group / design_effect
        return power_two_proportions(p_ref, p2, eff_n, eff_n, alpha)["power"] >= power

    best = None
    for direction in (1, -1):
        lo, hi = p_ref, (1.0 if direction > 0 else 0.0)
        if not ok(hi):
            continue
        for _ in range(60):
            mid = (lo + hi) / 2
            if ok(mid):
                hi = mid
            else:
                lo = mid
        cand = abs(hi - p_ref)
        best = cand if best is None else min(best, cand)
    return {"p_ref": p_ref, "n_per_group": n_per_group, "mde_abs": best,
            "alpha": alpha, "power": power, "design_effect": design_effect}


# ---------------------------------------------------------------------------
# Two-phase clinician review burden
# ---------------------------------------------------------------------------

def two_phase_review_burden(n_valid: int, screen_positive_rate: float,
                            neg_sample_rate: float) -> dict:
    """Expected number of outputs clinicians must label under the two-phase
    design: all screen-positives + a sampled fraction of screen-negatives.
    Two clinicians per item, so packets ≈ 2× reviewed."""
    pos = n_valid * screen_positive_rate
    neg_reviewed = n_valid * (1 - screen_positive_rate) * neg_sample_rate
    reviewed = pos + neg_reviewed
    return {"n_valid": n_valid, "expected_reviewed": math.ceil(reviewed),
            "expected_positive": math.ceil(pos), "expected_negative_sampled": math.ceil(neg_reviewed),
            "clinician_labels": math.ceil(reviewed) * 2,
            "screen_positive_rate": screen_positive_rate, "neg_sample_rate": neg_sample_rate}


def rule_of_three_n(target_upper: float) -> dict:
    """Attempts needed so that, if zero events occur, the 95% upper bound (3/n)
    is at or below `target_upper` — the planning rule for a rare/zero-event CHR."""
    n = math.ceil(3.0 / target_upper) if target_upper > 0 else None
    return {"target_upper": target_upper, "n": n,
            "note": "if 0 events in n, the 95% upper bound is ~3/n"}
