"""Tests for app/feed_diversify.py (BUG-021)."""

from app.feed_diversify import (
    MAX_FETCH_ROWS, cap_per_source, effective_source_cap, fetch_budget,
    page_slice,
)


def _row(article_id, source_id):
    return {"id": article_id, "source_id": source_id}


def test_cap_zero_returns_all_rows_unchanged():
    rows = [_row(i, i % 3) for i in range(10)]
    assert cap_per_source(rows, cap=0) == rows


def test_cap_negative_returns_all_rows_unchanged():
    rows = [_row(i, i % 3) for i in range(10)]
    assert cap_per_source(rows, cap=-1) == rows


def test_cap_drops_overflow_per_source_preserving_order():
    # source 1 has 5 articles; source 2 has 2 articles; cap=2
    rows = [
        _row(1, 1), _row(2, 1), _row(3, 1), _row(4, 2),
        _row(5, 1), _row(6, 2), _row(7, 1),
    ]
    got = cap_per_source(rows, cap=2)
    assert [r["id"] for r in got] == [1, 2, 4, 6]


def test_cap_one_keeps_first_only_per_source():
    rows = [_row(1, 1), _row(2, 2), _row(3, 1), _row(4, 2), _row(5, 3)]
    got = cap_per_source(rows, cap=1)
    assert [r["id"] for r in got] == [1, 2, 5]


def test_cap_handles_empty_input():
    assert cap_per_source([], cap=3) == []


def test_cap_handles_missing_source_id_key_as_a_group():
    # rows without the key collapse into a single None group
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    got = cap_per_source(rows, cap=2)
    assert [r["id"] for r in got] == [1, 2]


def test_cap_custom_key():
    rows = [
        {"id": 1, "category": "tech"},
        {"id": 2, "category": "tech"},
        {"id": 3, "category": "sports"},
        {"id": 4, "category": "tech"},
    ]
    got = cap_per_source(rows, cap=1, key="category")
    assert [r["id"] for r in got] == [1, 3]


def test_fetch_budget_zero_cap_is_exact():
    assert fetch_budget(page=1, page_size=30, cap=0) == 30
    assert fetch_budget(page=3, page_size=30, cap=0) == 90


def test_fetch_budget_overfetches_enough_to_fill_page_at_cap():
    # cap=3, page_size=30 → need at least 10 distinct sources to fill 30.
    # multiplier should be ceil(30/3)+1 = 11, so fetch_budget(1,30,3) >= 30*11.
    assert fetch_budget(page=1, page_size=30, cap=3) >= 30 * 11
    assert fetch_budget(page=2, page_size=30, cap=3) >= 60 * 11


def test_fetch_budget_multiplier_floored_at_two():
    # large cap means little over-fetch is needed, but never less than 2x
    # so a brief same-source run can't starve the page.
    assert fetch_budget(page=1, page_size=10, cap=100) == 10 * 2


def test_page_slice_returns_requested_window():
    rows = [{"id": i} for i in range(100)]
    assert [r["id"] for r in page_slice(rows, page=1, page_size=30)] == list(range(0, 30))
    assert [r["id"] for r in page_slice(rows, page=2, page_size=30)] == list(range(30, 60))
    assert [r["id"] for r in page_slice(rows, page=4, page_size=30)] == list(range(90, 100))


def test_page_slice_past_end_returns_empty():
    rows = [{"id": i} for i in range(10)]
    assert page_slice(rows, page=5, page_size=30) == []


def test_pagination_stable_across_pages():
    # 5 sources, 20 articles each, all interleaved (round-robin order in).
    # Cap=3 means each source contributes its first 3 → 15 survivors total.
    rows = []
    for round_i in range(20):
        for src in range(5):
            rows.append(_row(round_i * 5 + src, src))
    capped = cap_per_source(rows, cap=3)
    assert len(capped) == 15
    page1 = page_slice(capped, page=1, page_size=10)
    page2 = page_slice(capped, page=2, page_size=10)
    # No overlap; together they reproduce the full capped list.
    ids1 = [r["id"] for r in page1]
    ids2 = [r["id"] for r in page2]
    assert set(ids1).isdisjoint(ids2)
    assert ids1 + ids2 == [r["id"] for r in capped]


def test_burst_from_one_source_does_not_dominate():
    # 50 rows from source 1 in a row, then 30 from other sources.
    # With cap=3, source 1 contributes only 3 rows to the page.
    rows = [_row(i, 1) for i in range(50)] + [_row(50 + i, 2 + (i % 10)) for i in range(30)]
    capped = cap_per_source(rows, cap=3)
    src_1_count = sum(1 for r in capped if r["source_id"] == 1)
    assert src_1_count == 3


def test_effective_source_cap_unique_sources_on_returns_one():
    assert effective_source_cap({"unique_sources": True}, default_cap=3) == 1
    assert effective_source_cap({"unique_sources": 1}, default_cap=3) == 1


def test_effective_source_cap_unique_sources_off_returns_default():
    assert effective_source_cap({"unique_sources": False}, default_cap=3) == 3
    assert effective_source_cap({"unique_sources": 0}, default_cap=3) == 3
    assert effective_source_cap({}, default_cap=3) == 3


def test_effective_source_cap_overrides_disabled_default():
    # When the global cap is disabled (0) the toggle still tightens to 1.
    assert effective_source_cap({"unique_sources": True}, default_cap=0) == 1


def test_effective_source_cap_handles_none_weights():
    assert effective_source_cap(None, default_cap=3) == 3
    assert effective_source_cap(None, default_cap=0) == 0


def test_effective_source_cap_does_not_weaken_tighter_default():
    # If a future operator sets default_cap=1 globally, the toggle is a no-op.
    assert effective_source_cap({"unique_sources": True}, default_cap=1) == 1
    # And toggle-off doesn't weaken it either — default_cap is the floor.
    assert effective_source_cap({}, default_cap=1) == 1


def test_unique_sources_yields_no_duplicate_source_ids():
    # Regression: cap_per_source with cap=1 leaves at most one row per source.
    rows = [_row(i, i // 4) for i in range(20)]  # 4 rows per source × 5 sources
    capped = cap_per_source(rows, cap=1)
    src_ids = [r["source_id"] for r in capped]
    assert len(src_ids) == len(set(src_ids))
    assert sorted(src_ids) == [0, 1, 2, 3, 4]


def test_fetch_budget_grows_for_cap_one():
    # cap=1, page_size=30 → multiplier ≥ 31, so page 1 needs ≥ 930 rows.
    assert fetch_budget(page=1, page_size=30, cap=1) >= 30 * 31


def test_max_fetch_rows_is_a_sensible_ceiling():
    # The ceiling exists to bound deep "Load more" paging under cap=1.
    # At least enough for a few full pages, but not unbounded.
    assert MAX_FETCH_ROWS >= 30 * 31
    assert MAX_FETCH_ROWS <= 50_000
