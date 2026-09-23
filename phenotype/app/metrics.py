"""Diagnostic-accuracy statistics (pure stdlib).

Proportions (sensitivity, specificity, PPV, NPV) are pooled on the logit
scale with a DerSimonian-Laird random-effects model. Each study estimate
enters as (logit p, var) derived, in order of preference, from the 2x2
counts, from the reported 95% CI, or from p and the denominator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Z = 1.959963984540054
_EPS = 1e-4


def _clip(p: float) -> float:
    return min(1 - _EPS, max(_EPS, p))


def logit(p: float) -> float:
    p = _clip(p)
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def wilson(x: float, n: float, z: float = Z) -> tuple[float, float, float]:
    """Wilson score interval. Returns (p, lo, hi)."""
    if n <= 0:
        return (float("nan"),) * 3
    p = x / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Estimate:
    """One study's estimate of one proportion, on the logit scale."""
    y: float      # logit(p)
    v: float      # variance of logit(p)
    n: float      # denominator (actual or effective)
    source: str   # "counts" | "ci" | "n"


def to_logit_estimate(value: float | None = None, lo: float | None = None, hi: float | None = None,
                      x: float | None = None, n: float | None = None) -> Estimate | None:
    """Best available logit-scale estimate; None when nothing usable."""
    if x is not None and n and 0 <= x <= n:
        # Haldane-Anscombe 0.5 correction keeps 0 or n cells finite.
        return Estimate(math.log((x + 0.5) / (n - x + 0.5)), 1 / (x + 0.5) + 1 / (n - x + 0.5), n, "counts")
    if value is None or not 0 <= value <= 1:
        return None
    if lo is not None and hi is not None and 0 <= lo < hi <= 1 and lo <= value <= hi:
        se = (logit(hi) - logit(lo)) / (2 * Z)
        if se > 0:
            p = _clip(value)
            n_eff = 1 / (se * se * p * (1 - p))
            return Estimate(logit(value), se * se, n_eff, "ci")
    if n and n > 0:
        xx = value * n
        return Estimate(math.log((xx + 0.5) / (n - xx + 0.5)), 1 / (xx + 0.5) + 1 / (n - xx + 0.5), n, "n")
    return None


def pool(estimates: list[Estimate]) -> dict | None:
    """DerSimonian-Laird random-effects pool on the logit scale.

    Returns value / lo / hi on the probability scale plus k, tau^2, I^2 and
    the total denominator. With one study it is that study's estimate.
    """
    est = [e for e in estimates if e and e.v > 0]
    if not est:
        return None
    k = len(est)
    w = [1 / e.v for e in est]
    sw = sum(w)
    y_fe = sum(wi * e.y for wi, e in zip(w, est)) / sw
    q = sum(wi * (e.y - y_fe) ** 2 for wi, e in zip(w, est))
    df = k - 1
    c = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (q - df) / c) if k > 1 and c > 0 else 0.0
    i2 = max(0.0, (q - df) / q) if k > 1 and q > 0 else 0.0
    wr = [1 / (e.v + tau2) for e in est]
    swr = sum(wr)
    y = sum(wi * e.y for wi, e in zip(wr, est)) / swr
    se = math.sqrt(1 / swr)
    return {"value": expit(y), "lo": expit(y - Z * se), "hi": expit(y + Z * se),
            "k": k, "tau2": tau2, "i2": i2, "n": round(sum(e.n for e in est))}


def ppv_at(se: float, sp: float, prev: float) -> float | None:
    den = se * prev + (1 - sp) * (1 - prev)
    return None if den <= 0 else se * prev / den


def npv_at(se: float, sp: float, prev: float) -> float | None:
    den = sp * (1 - prev) + (1 - se) * prev
    return None if den <= 0 else sp * (1 - prev) / den


def apparent_prevalence(se: float, sp: float, prev: float) -> float:
    return se * prev + (1 - sp) * (1 - prev)


def rogan_gladen(apparent: float, se: float, sp: float) -> float | None:
    """True prevalence from algorithm-apparent prevalence, given Se/Sp."""
    j = se + sp - 1
    if j <= 0:
        return None
    return min(1.0, max(0.0, (apparent + sp - 1) / j))
