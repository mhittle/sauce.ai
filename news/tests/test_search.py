"""Tests for the full-text article search helpers.

Mirrors test_feed_sort.py: the route SQL needs Flask + pymysql (exercised
on CI / a real env), but the query-normalization helpers are pure and
unit-tested here.
"""
from app.routes.search import clean_query, parse_page, PAGE_SIZE, MAX_QUERY_LEN


def test_clean_query_trims_and_collapses_whitespace():
    assert clean_query("  hello   world  ") == "hello world"
    assert clean_query("a\tb\nc") == "a b c"


def test_clean_query_blank_and_none_become_empty():
    for blank in (None, "", "   ", "\t\n", 0, False):
        assert clean_query(blank) == ""


def test_clean_query_caps_length():
    long = "x" * (MAX_QUERY_LEN + 50)
    assert len(clean_query(long)) == MAX_QUERY_LEN


def test_clean_query_caps_length_after_collapsing():
    # Collapsing happens before the cap, so internal runs don't eat the budget.
    raw = ("ab   " * 100)
    cleaned = clean_query(raw)
    assert len(cleaned) <= MAX_QUERY_LEN
    assert "   " not in cleaned


def test_clean_query_coerces_non_str():
    assert clean_query(12345) == "12345"


def test_parse_page_valid():
    assert parse_page("1") == 1
    assert parse_page("7") == 7
    assert parse_page(3) == 3


def test_parse_page_defaults_to_one_for_bad_input():
    for bad in (None, "", "abc", "1.5", "-2", "0", [], {}):
        assert parse_page(bad) == 1


def test_constants_sane():
    assert PAGE_SIZE > 0
    assert MAX_QUERY_LEN >= 50
