"""Tests for per-algorithm keyword mute & boost SQL builders.

Pure (no Flask / no DB), same convention as test_ranking /
test_feed_sort / test_trending — runs anywhere.
"""
from app.term_prefs import (
    normalize_term,
    clamp_boost,
    escape_like,
    build_term_clauses,
    BOOST_DEFAULT,
    BOOST_MIN,
    BOOST_MAX,
)


# --- normalize_term -------------------------------------------------

def test_normalize_lowercases_trims_and_collapses_whitespace():
    assert normalize_term("  Royal   Family  ") == "royal family"
    assert normalize_term("CRYPTO") == "crypto"


def test_normalize_rejects_empty_and_too_short():
    for bad in (None, "", "   ", "a", " x "):
        assert normalize_term(bad) is None


def test_normalize_caps_length():
    out = normalize_term("z" * 500)
    assert out is not None and len(out) == 128


# --- clamp_boost ----------------------------------------------------

def test_clamp_boost_clamps_into_range():
    assert clamp_boost(0.1) == BOOST_MIN
    assert clamp_boost(99) == BOOST_MAX
    assert clamp_boost(2.0) == 2.0


def test_clamp_boost_defaults_on_garbage():
    for bad in (None, "", "abc", object()):
        assert clamp_boost(bad) == BOOST_DEFAULT


# --- escape_like ----------------------------------------------------

def test_escape_like_escapes_metacharacters():
    assert escape_like("100%") == "100\\%"
    assert escape_like("a_b") == "a\\_b"
    # Backslash doubled first so the % escape isn't itself re-escaped.
    assert escape_like("a\\%") == "a\\\\\\%"


# --- build_term_clauses --------------------------------------------

def test_empty_prefs_yield_no_sql():
    mute_sql, boost_expr, params = build_term_clauses([])
    assert mute_sql == ""
    assert boost_expr == ""
    assert params == {}


def test_none_prefs_safe():
    assert build_term_clauses(None) == ("", "", {})


def test_mute_builds_negated_like_and_param():
    mute_sql, boost_expr, params = build_term_clauses(
        [{"term": "Crypto", "mode": "mute"}]
    )
    assert mute_sql.startswith(" AND NOT (")
    assert "LIKE %(term_mute_0)s ESCAPE" in mute_sql
    assert params["term_mute_0"] == "%crypto%"
    assert boost_expr == ""


def test_boost_builds_greatest_case_with_weight():
    mute_sql, boost_expr, params = build_term_clauses(
        [{"term": "climate policy", "mode": "boost", "weight": 2.0}]
    )
    assert mute_sql == ""
    assert boost_expr.startswith("GREATEST(1.0,")
    assert "CASE WHEN" in boost_expr
    assert "THEN %(term_boost_w_0)s ELSE 0 END" in boost_expr
    assert params["term_boost_0"] == "%climate policy%"
    assert params["term_boost_w_0"] == 2.0


def test_boost_weight_defaulted_and_clamped():
    _, _, p_default = build_term_clauses([{"term": "x ray", "mode": "boost"}])
    assert p_default["term_boost_w_0"] == BOOST_DEFAULT
    _, _, p_big = build_term_clauses(
        [{"term": "x ray", "mode": "boost", "weight": 999}]
    )
    assert p_big["term_boost_w_0"] == BOOST_MAX


def test_mute_and_boost_together():
    mute_sql, boost_expr, params = build_term_clauses([
        {"term": "crypto", "mode": "mute"},
        {"term": "climate", "mode": "boost", "weight": 1.8},
    ])
    assert "term_mute_0" in params
    assert "term_boost_0" in params
    assert mute_sql and boost_expr


def test_mute_wins_when_same_term_in_both_lists():
    mute_sql, boost_expr, params = build_term_clauses([
        {"term": "Politics", "mode": "boost", "weight": 3.0},
        {"term": "politics", "mode": "mute"},
    ])
    assert params.get("term_mute_0") == "%politics%"
    assert boost_expr == ""
    assert not any(k.startswith("term_boost_") for k in params)


def test_short_or_blank_terms_are_skipped():
    mute_sql, boost_expr, params = build_term_clauses([
        {"term": "a", "mode": "mute"},
        {"term": "   ", "mode": "boost"},
    ])
    assert (mute_sql, boost_expr, params) == ("", "", {})


def test_duplicate_terms_collapse_to_one_clause():
    mute_sql, _, params = build_term_clauses([
        {"term": "crypto", "mode": "mute"},
        {"term": " CRYPTO ", "mode": "mute"},
    ])
    mute_keys = [k for k in params if k.startswith("term_mute_")]
    assert mute_keys == ["term_mute_0"]


def test_user_term_is_parameterized_not_inlined():
    """A term containing SQL must never appear in the generated SQL text
    — it rides in params, escaped, so injection is impossible."""
    payload = "'); DROP TABLE articles;--"
    mute_sql, _, params = build_term_clauses(
        [{"term": payload, "mode": "mute"}]
    )
    assert "DROP TABLE" not in mute_sql
    assert params["term_mute_0"] == f"%{payload.lower()}%"


def test_multiple_boosts_indexed_distinctly():
    _, boost_expr, params = build_term_clauses([
        {"term": "alpha", "mode": "boost", "weight": 1.2},
        {"term": "beta", "mode": "boost", "weight": 1.4},
    ])
    assert params["term_boost_0"] and params["term_boost_1"]
    assert boost_expr.count("CASE WHEN") == 2


