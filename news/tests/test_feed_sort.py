"""Tests for the feed sort selector (Relevance / Newest / Popularity)."""
from app.routes.feed import (
    SORT_OPTIONS,
    SORT_LABELS,
    _normalize_sort,
    _order_by_for_sort,
)


def test_sort_options_are_the_three_documented():
    assert SORT_OPTIONS == ("relevance", "newest", "popularity")
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
    assert _normalize_sort("  POPULARITY  ") == "popularity"


def test_order_by_relevance_sorts_by_score_first():
    sql = _order_by_for_sort("relevance")
    assert sql.startswith("ORDER BY")
    assert "score DESC" in sql
    assert sql.index("score") < sql.index("published_at")


def test_order_by_newest_sorts_by_published_at_first():
    sql = _order_by_for_sort("newest")
    assert sql.startswith("ORDER BY")
    assert "a.published_at DESC" in sql
    assert sql.index("published_at") < sql.index("score")


def test_order_by_popularity_sorts_by_popularity_first():
    sql = _order_by_for_sort("popularity")
    assert sql.startswith("ORDER BY")
    assert "f.popularity DESC" in sql
    # Popularity ties break on recency, not on score.
    assert "score" not in sql


def test_order_by_unknown_falls_back_to_relevance():
    """If a future bug ever feeds an unnormalized value here, fail safe."""
    assert _order_by_for_sort("bogus") == _order_by_for_sort("relevance")
