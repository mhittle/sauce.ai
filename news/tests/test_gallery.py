"""Pure tests for the shareable-algorithm gallery helpers.

No Flask / no DB — same convention as test_term_prefs / test_spectrum /
test_firehose_cursor.
"""
from app.gallery import (
    clean_listing_name,
    clean_description,
    normalize_sort,
    sort_order_by,
    normalize_search,
    escape_like,
    SORT_KEYS,
    SORT_ORDER_BY,
    DEFAULT_SORT,
    MAX_NAME_LEN,
    MAX_DESCRIPTION_LEN,
    MAX_SEARCH_LEN,
    NAME_FALLBACK,
)


# --- clean_listing_name -----------------------------------------------

def test_clean_listing_name_trims_and_caps():
    assert clean_listing_name("   My Feed   ") == "My Feed"
    long = "z" * (MAX_NAME_LEN + 50)
    out = clean_listing_name(long)
    assert len(out) == MAX_NAME_LEN


def test_clean_listing_name_fallback_on_empty():
    assert clean_listing_name("") == NAME_FALLBACK
    assert clean_listing_name(None) == NAME_FALLBACK
    assert clean_listing_name("   ") == NAME_FALLBACK


def test_clean_listing_name_custom_fallback():
    assert clean_listing_name(None, fallback="X") == "X"
    assert clean_listing_name("ok", fallback="X") == "ok"


# --- clean_description ------------------------------------------------

def test_clean_description_trims_and_caps():
    assert clean_description("  hi  ") == "hi"
    long = "z" * (MAX_DESCRIPTION_LEN + 100)
    assert len(clean_description(long)) == MAX_DESCRIPTION_LEN


def test_clean_description_empty():
    assert clean_description("") == ""
    assert clean_description(None) == ""


# --- normalize_sort + sort_order_by -----------------------------------

def test_normalize_sort_known_keys_pass_through():
    for k in SORT_KEYS:
        assert normalize_sort(k) == k
        assert normalize_sort(k.upper()) == k
        assert normalize_sort(f"  {k}  ") == k


def test_normalize_sort_unknown_falls_back():
    for bad in (None, "", "garbage", "1; DROP TABLE", "popularity"):
        assert normalize_sort(bad) == DEFAULT_SORT


def test_sort_order_by_returns_fixed_fragment_per_key():
    seen = set()
    for k in SORT_KEYS:
        frag = sort_order_by(k)
        assert frag == SORT_ORDER_BY[k]
        seen.add(frag)
    assert len(seen) == len(SORT_KEYS)


def test_sort_order_by_ignores_user_injection():
    """The function must always return a literal from the fixed map —
    never reflect user input into the SQL string."""
    bad = "popular; DROP TABLE shared_algorithms; --"
    assert sort_order_by(bad) == SORT_ORDER_BY[DEFAULT_SORT]


# --- normalize_search -------------------------------------------------

def test_normalize_search_trims_and_caps():
    assert normalize_search("  hello  ") == "hello"
    assert normalize_search("") == ""
    assert normalize_search(None) == ""
    long = "x" * (MAX_SEARCH_LEN + 50)
    assert len(normalize_search(long)) == MAX_SEARCH_LEN


# --- escape_like ------------------------------------------------------

def test_escape_like_handles_metacharacters_in_order():
    # Backslash must double FIRST so the escape sequences we add for %/_
    # aren't themselves re-escaped.
    assert escape_like("a\\b") == "a\\\\b"
    assert escape_like("100%") == "100\\%"
    assert escape_like("foo_bar") == "foo\\_bar"
    assert escape_like("a\\%_b") == "a\\\\\\%\\_b"
    assert escape_like("clean") == "clean"
