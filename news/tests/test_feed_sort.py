"""Tests for the feed sort selector (Relevance / Newest / Trending).

`trending` replaced the old raw `popularity` sort in BUG-015; the
legacy value is aliased so old links keep working.
"""
import datetime

from app.routes.feed import (
    SORT_OPTIONS,
    SORT_LABELS,
    _normalize_sort,
)
from app.feed_diversify import rank_for_display


def test_sort_options_are_the_three_documented():
    assert SORT_OPTIONS == ("relevance", "newest", "trending")
    for opt in SORT_OPTIONS:
        assert opt in SORT_LABELS and SORT_LABELS[opt]


def test_normalize_sort_passes_through_valid_options():
    for opt in SORT_OPTIONS:
        assert _normalize_sort(opt) == opt


def test_normalize_sort_falls_back_to_relevance_for_unknown():
    for bad in (None, "", "  ", "score", "foo", "DROP TABLE", "newst"):
        assert _normalize_sort(bad) == "relevance"


def test_normalize_sort_is_case_insensitive_and_trimmed():
    assert _normalize_sort("Newest") == "newest"
    assert _normalize_sort("  TRENDING  ") == "trending"


def test_legacy_popularity_value_aliases_to_trending():
    """Old `?sort=popularity` bookmarks / digest links must not silently
    fall back to relevance after the BUG-015 rename."""
    assert _normalize_sort("popularity") == "trending"
    assert _normalize_sort("  Popularity ") == "trending"


# BUG-030: ordering for display is now a pure post-selection re-sort
# (`rank_for_display`), distinct from affinity *selection* which the SQL
# does. These pin the per-sort ordering semantics the SQL ORDER BY used to.

def _rows():
    """Three rows that disagree on score / freshness / trending so each sort
    produces a distinct order."""
    old = datetime.datetime(2026, 5, 1, 12, 0, 0)
    new = datetime.datetime(2026, 5, 31, 12, 0, 0)
    mid = datetime.datetime(2026, 5, 15, 12, 0, 0)
    return [
        {"id": 1, "score": 0.9, "trending": 0.1, "published_at": old},
        {"id": 2, "score": 0.5, "trending": 0.9, "published_at": new},
        {"id": 3, "score": 0.7, "trending": 0.5, "published_at": mid},
    ]


def test_rank_relevance_orders_by_score_desc():
    out = rank_for_display(_rows(), "relevance")
    assert [r["id"] for r in out] == [1, 3, 2]  # 0.9, 0.7, 0.5


def test_rank_newest_orders_by_published_at_desc():
    out = rank_for_display(_rows(), "newest")
    assert [r["id"] for r in out] == [2, 3, 1]  # new, mid, old


def test_rank_trending_orders_by_trending_then_score():
    out = rank_for_display(_rows(), "trending")
    assert [r["id"] for r in out] == [2, 3, 1]  # 0.9, 0.5, 0.1


def test_rank_unknown_sort_falls_back_to_relevance():
    rows = _rows()
    assert rank_for_display(rows, "bogus") == rank_for_display(rows, "relevance")


def test_rank_is_stable_on_ties():
    """Equal sort keys preserve incoming (affinity) order — Python stable sort."""
    rows = [
        {"id": 10, "score": 0.5, "published_at": datetime.datetime(2026, 5, 1)},
        {"id": 11, "score": 0.5, "published_at": datetime.datetime(2026, 5, 1)},
        {"id": 12, "score": 0.5, "published_at": datetime.datetime(2026, 5, 1)},
    ]
    assert [r["id"] for r in rank_for_display(rows, "relevance")] == [10, 11, 12]


def test_rank_tolerates_missing_and_null_keys():
    """A null published_at or absent trending/score must not raise."""
    rows = [
        {"id": 1, "score": None, "published_at": None},
        {"id": 2, "score": 0.4, "published_at": datetime.datetime(2026, 5, 2)},
    ]
    for sort in ("relevance", "newest", "trending"):
        out = rank_for_display(rows, sort)
        assert {r["id"] for r in out} == {1, 2}
