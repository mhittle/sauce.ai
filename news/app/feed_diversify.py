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

import datetime
from typing import Iterable, Mapping, Sequence

# Sort key fallback for rows with a null publication time, so a mixed
# datetime/None column still orders deterministically.
_MIN_DT = datetime.datetime.min

# Hard ceiling for the per-request fetch. The feed selects a fixed
# FEED_SELECTION_POOL of affinity-ranked rows (BUG-028); clamp it here so a
# misconfigured pool can't issue an unbounded `LIMIT`. Deep "Load more"
# paging past the pool comes up short rather than scanning the whole window.
MAX_FETCH_ROWS = 5000


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


def page_slice(rows: Sequence[dict], page: int, page_size: int) -> list[dict]:
    """Slice `rows[(page-1)*page_size : page*page_size]`."""
    start = (page - 1) * page_size
    end = page * page_size
    return list(rows[start:end])


def _num(row: Mapping, key: str) -> float:
    v = row.get(key)
    return float(v) if isinstance(v, (int, float)) else 0.0


def rank_for_display(rows: Iterable[dict], sort: str) -> list[dict]:
    """Order an already-SELECTED candidate set for display (BUG-028).

    Selection (membership — *which* articles are in the list) is done
    upstream by affinity: what the algorithm cares about. This is the
    separate *ranking* stage — the order the chosen articles are shown in —
    keyed on the user's sort:

      relevance -> recency-gated algo `score`, freshest-and-best first
      newest    -> `published_at`
      trending  -> external `trending` heat

    All three are descending with the algo `score` as a stable tiebreak;
    Python's sort is stable so equal keys preserve the incoming
    (affinity) order. Pure: no Flask, no DB.
    """
    if sort == "newest":
        key = lambda r: (r.get("published_at") or _MIN_DT, _num(r, "score"))
    elif sort == "trending":
        key = lambda r: (_num(r, "trending"), _num(r, "score"))
    else:  # relevance (default / unknown)
        key = lambda r: (_num(r, "score"), r.get("published_at") or _MIN_DT)
    return sorted(rows, key=key, reverse=True)


def effective_source_cap(weights: Mapping | None, default_cap: int) -> int:
    """Per-profile `unique_sources` toggle tightens the global cap to 1.

    When the active profile's weights carry `unique_sources` truthy the
    feed shows at most one article per source regardless of the global
    `FEED_MAX_PER_SOURCE` config (including when it is 0/disabled).
    Otherwise return `default_cap` unchanged.
    """
    if weights and weights.get("unique_sources"):
        return 1
    return default_cap
