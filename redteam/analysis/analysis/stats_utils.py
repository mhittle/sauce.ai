"""Small statistics helpers that stay pure stdlib (tested in-env)."""
from __future__ import annotations


def benjamini_hochberg(pvals: list[float], alpha: float = 0.05) -> dict:
    """Benjamini–Hochberg FDR. Returns adjusted p-values (q-values) in the input
    order and the set of rejected indices at level ``alpha``. None p-values are
    carried through as None and excluded from the procedure."""
    idx = [i for i, p in enumerate(pvals) if p is not None]
    m = len(idx)
    q: list[float | None] = [None] * len(pvals)
    if m == 0:
        return {"q": q, "rejected": [], "m": 0}
    ordered = sorted(idx, key=lambda i: pvals[i])
    # step-up: q_(k) = min over j>=k of (m/j) * p_(j), clamped to <=1
    running = 1.0
    for rank in range(m, 0, -1):
        i = ordered[rank - 1]
        val = min(1.0, pvals[i] * m / rank)
        running = min(running, val)
        q[i] = running
    rejected = [i for i in idx if q[i] is not None and q[i] <= alpha]
    return {"q": q, "rejected": sorted(rejected), "m": m}
