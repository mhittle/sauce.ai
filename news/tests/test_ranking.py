import re
from app.ranking import (
    build_score_sql, build_filters_sql, default_weights,
    weights_to_expression, parse_weights_json, PRESETS, FEATURE_KEYS,
)


def test_default_weights_has_required_keys():
    w = default_weights()
    for k in ("objectivity", "info_density", "source_reputation"):
        assert k in w


def test_build_score_sql_includes_active_features():
    w = {"objectivity": 1.5, "info_density": 0.5, "recency": 0.7}
    expr, params = build_score_sql(w)
    assert "f.objectivity" in expr
    assert "f.info_density" in expr
    assert "EXP(" in expr
    assert params["objectivity_w"] == 1.5
    assert params["recency_w"] == 0.7


def test_build_score_sql_signed_feature_uses_target():
    w = {"political_lean": 1.0, "political_lean_target": -0.3}
    expr, params = build_score_sql(w)
    assert "f.political_lean" in expr
    assert "ABS" in expr
    assert params["political_lean_t"] == -0.3


def test_zero_weight_feature_is_excluded():
    w = {"objectivity": 0, "info_density": 0.4}
    expr, _ = build_score_sql(w)
    assert "f.info_density" in expr
    assert "f.objectivity" not in expr


def test_build_filters_sql_category():
    w = {"category_filter": ["tech", "science"]}
    sql, params = build_filters_sql(w)
    assert "f.category IN" in sql
    assert "tech" in params.values()


def test_no_filters_returns_empty():
    sql, params = build_filters_sql({})
    assert sql == ""
    assert params == {}


def test_weights_to_expression_renders_python():
    w = {"objectivity": 0.8, "info_density": 0.5, "political_lean": 1.0, "political_lean_target": 0.0}
    out = weights_to_expression(w)
    assert "def score(article)" in out
    assert "article.objectivity" in out
    assert "article.political_lean" in out


def test_parse_weights_json_invalid_returns_default():
    w = parse_weights_json("not json")
    assert isinstance(w, dict)
    assert "objectivity" in w


def test_presets_all_valid():
    for key, p in PRESETS.items():
        expr, _ = build_score_sql(p["weights"])
        assert isinstance(expr, str) and len(expr) > 0
