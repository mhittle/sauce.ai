"""Per-source diversification cap for the home feed (BUG-021).

The feed query orders by score (or recency/trending) and takes the top N.
Without diversification, a single source with a recent fetch burst or an
elevated `source_reputation` can crowd out the rest of the catalog across
algorithms. This helper enforces "at most N articles from any one source
per page" in Python so the SQL stays version-agnostic (no window function
required) and the logic is unit-testable.

The cap is applied AFTER the SQL ORDER BY so the survivors preserve the
ranking that brought them in. Pagination is implemented by capping the
prefix corresponding to `page * page_size`, then slicing the requested
page out of the capped sequence — so page N+1 sees a stable view that
agrees with page N.
"""

from __future__ import annotations

from typing import Iterable, Sequence


def cap_per_source(
    rows: Iterable[dict],
    *,
    cap: int,
    key: str = "source_id",
) -> list[dict]:
    """Keep at most `cap` rows per `key` value, preserving input order.

    `cap <= 0` returns the input unchanged (cap disabled).
    """
    if cap <= 0:
        return list(rows)
    seen: dict = {}
    out: list[dict] = []
    for r in rows:
        k = r.get(key)
        n = seen.get(k, 0)
        if n >= cap:
            continue
        seen[k] = n + 1
        out.append(r)
    return out


def fetch_budget(page: int, page_size: int, cap: int) -> int:
    """SQL row budget needed to guarantee `page * page_size` capped rows.

    Worst case: every fetched row is from the same source — then we need
    `page * page_size * (something large)` rows to fill the page. With
    `cap=3` and `page_size=30` the worst case is unbounded, but in
    practice the catalog has hundreds of active sources; over-fetching
    by ~`ceil(page_size / cap) + 1` is plenty. We add a small constant
    cushion so a brief single-source burst doesn't starve the page.
    """
    if cap <= 0:
        return page * page_size
    multiplier = max(2, (page_size + cap - 1) // cap + 1)
    return page * page_size * multiplier


def page_slice(rows: Sequence[dict], page: int, page_size: int) -> list[dict]:
    """Slice `rows[(page-1)*page_size : page*page_size]`."""
    start = (page - 1) * page_size
    end = page * page_size
    return list(rows[start:end])
