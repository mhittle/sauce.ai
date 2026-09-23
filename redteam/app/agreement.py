"""Inter-rater agreement, diagnostic accuracy, and probability calibration —
the statistics behind the judge-validation study (RESEARCH.md §3).

Pure stdlib, no numpy/scipy, so every estimator is auditable and unit-tested.
Ratings are binary harmful/not-harmful unless a function says otherwise.
"""
from __future__ import annotations

import math

Z95 = 1.959963984540054


def _wilson(k: int, n: int, z: float = Z95):
    if n <= 0:
        return (None, None, None)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


# ---------------------------------------------------------------------------
# Inter-rater agreement
# ---------------------------------------------------------------------------

def percent_agreement(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    return sum(1 for x, y in pairs if x == y) / len(pairs)


def cohen_kappa(a: list, b: list) -> float | None:
    """Two raters, categorical labels. Returns None if undefined."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    cats = sorted({x for p in pairs for x in p}, key=str)
    n = len(pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    pe = 0.0
    for c in cats:
        pa = sum(1 for x, _ in pairs if x == c) / n
        pb = sum(1 for _, y in pairs if y == c) / n
        pe += pa * pb
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def gwet_ac1(a: list, b: list) -> float | None:
    """Gwet's AC1 — robust to the prevalence/kappa paradox when one label
    (here, 'not harmful') dominates. Two raters, categorical."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    cats = sorted({x for p in pairs for x in p}, key=str)
    q = len(cats)
    if q < 2:
        return 1.0
    n = len(pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    # per-category mean marginal probability across the two raters
    pk = {}
    for c in cats:
        pa = sum(1 for x, _ in pairs if x == c) / n
        pb = sum(1 for _, y in pairs if y == c) / n
        pk[c] = (pa + pb) / 2
    pe = sum(p * (1 - p) for p in pk.values()) / (q - 1)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def weighted_kappa(a: list[int], b: list[int], weights: str = "linear",
                   categories: list[int] | None = None) -> float | None:
    """Ordinal agreement (e.g. severity 0..4). weights: 'linear' or 'quadratic'."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    cats = categories or sorted({x for p in pairs for x in p})
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    if k < 2:
        return 1.0
    n = len(pairs)

    def w(i, j):
        d = abs(i - j) / (k - 1)
        return d * d if weights == "quadratic" else d

    obs = [[0.0] * k for _ in range(k)]
    for x, y in pairs:
        obs[idx[x]][idx[y]] += 1
    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            exp = row[i] * col[j] / n
            num += w(i, j) * obs[i][j]
            den += w(i, j) * exp
    if den == 0:
        return 1.0
    return 1 - num / den


# ---------------------------------------------------------------------------
# Diagnostic accuracy: automated judge vs a human reference label
# ---------------------------------------------------------------------------

def diagnostic(pred: list[bool], truth: list[bool]) -> dict:
    """Judge (pred) vs human reference (truth), both binary. Sensitivity,
    specificity, PPV, NPV, accuracy, prevalence — each with a Wilson CI."""
    pairs = [(bool(p), bool(t)) for p, t in zip(pred, truth) if p is not None and t is not None]
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    n = len(pairs)

    def ci(k, d):
        p, lo, hi = _wilson(k, d)
        return {"value": p, "lo": lo, "hi": hi, "n": d}

    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "prevalence": ci(tp + fn, n),
        "sensitivity": ci(tp, tp + fn),
        "specificity": ci(tn, tn + fp),
        "ppv": ci(tp, tp + fp),
        "npv": ci(tn, tn + fn),
        "accuracy": ci(tp + tn, n),
    }


def roc_auc(scores: list[float], truth: list[bool]) -> dict:
    """AUROC via the Mann–Whitney U statistic (rank sum), with mid-ranks for
    ties. Score is the judge's P(harm); truth is the human label."""
    pairs = [(float(s), bool(t)) for s, t in zip(scores, truth) if s is not None and t is not None]
    pos = [s for s, t in pairs if t]
    neg = [s for s, t in pairs if not t]
    if not pos or not neg:
        return {"auc": None, "n_pos": len(pos), "n_neg": len(neg)}
    order = sorted(pairs, key=lambda st: st[0])
    ranks = [0.0] * len(order)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][0] == order[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # ranks are 1-based
        for m in range(i, j + 1):
            ranks[m] = avg
        i = j + 1
    rank_pos = sum(r for r, (_, t) in zip(ranks, order) if t)
    n_pos, n_neg = len(pos), len(neg)
    u = rank_pos - n_pos * (n_pos + 1) / 2
    return {"auc": u / (n_pos * n_neg), "n_pos": n_pos, "n_neg": n_neg}


# ---------------------------------------------------------------------------
# Calibration of the judge's probabilities
# ---------------------------------------------------------------------------

def brier_score(probs: list[float], truth: list[bool]) -> float | None:
    pairs = [(float(p), 1.0 if t else 0.0) for p, t in zip(probs, truth) if p is not None and t is not None]
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def reliability_bins(probs: list[float], truth: list[bool], n_bins: int = 10) -> list[dict]:
    """Equal-width reliability-diagram bins over [0, 1]."""
    pairs = [(float(p), bool(t)) for p, t in zip(probs, truth) if p is not None and t is not None]
    bins = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        sel = [(p, t) for p, t in pairs if (p >= lo and (p < hi or (b == n_bins - 1 and p <= hi)))]
        if sel:
            conf = sum(p for p, _ in sel) / len(sel)
            acc = sum(1 for _, t in sel if t) / len(sel)
        else:
            conf = acc = None
        bins.append({"lo": lo, "hi": hi, "n": len(sel), "mean_pred": conf, "observed": acc})
    return bins


def expected_calibration_error(probs: list[float], truth: list[bool], n_bins: int = 10) -> float | None:
    pairs = [p for p, t in zip(probs, truth) if p is not None and t is not None]
    if not pairs:
        return None
    total = len(pairs)
    ece = 0.0
    for b in reliability_bins(probs, truth, n_bins):
        if b["n"]:
            ece += (b["n"] / total) * abs(b["mean_pred"] - b["observed"])
    return ece


# ---------------------------------------------------------------------------
# Fleiss' kappa for ≥3 raters (binary), re-exported for the panel case
# ---------------------------------------------------------------------------

def fleiss_kappa(ratings: list[list[bool]]) -> float | None:
    rows = [r for r in ratings if len(r) >= 2]
    if not rows or len({len(r) for r in rows}) != 1:
        return None
    m = len(rows[0])
    n = len(rows)
    p_yes = sum(sum(r) for r in rows) / (n * m)
    p_e = p_yes ** 2 + (1 - p_yes) ** 2
    p_bar = sum((sum(r) ** 2 + (m - sum(r)) ** 2 - m) / (m * (m - 1)) for r in rows) / n
    if p_e >= 1:
        return 1.0
    return (p_bar - p_e) / (1 - p_e)


def majority_vote(labels: list[bool]) -> bool | None:
    vals = [bool(x) for x in labels if x is not None]
    if not vals:
        return None
    yes = sum(vals)
    if yes * 2 == len(vals):
        return None  # tie → undecided; caller sends to a tiebreaker
    return yes * 2 > len(vals)
