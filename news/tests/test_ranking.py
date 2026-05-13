from app.ranking import (
    build_score_sql, build_filters_sql, default_weights,
    weights_to_expression, parse_weights_json, PRESETS, FEATURE_KEYS,
    FEATURES, resolved_weights_for_view,
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


def test_recency_is_multiplicative_gate():
    """BUG-011: recency must multiply the quality score, not just add a small term.
    Otherwise a stack of high-quality static features can outweigh freshness."""
    w = {"objectivity": 1.0, "recency": 0.7}
    expr, _ = build_score_sql(w)
    # The quality sum is parenthesised and multiplied by EXP(...).
    assert ") * EXP(" in expr.replace("\n", " ")
    # No additive recency term left over.
    assert "+ (%(recency_w)s" not in expr


def test_recency_zero_disables_decay():
    w = {"objectivity": 1.0, "recency": 0}
    expr, params = build_score_sql(w)
    assert "EXP(" not in expr
    assert "recency_w" not in params


def test_recency_alone_without_quality_features():
    w = {"recency": 1.0}
    expr, params = build_score_sql(w)
    assert "EXP(" in expr
    assert params["recency_w"] == 1.0


def test_build_score_sql_uses_direction_for_all_features():
    w = {"political_lean": 1.0, "political_lean_direction": -0.3,
         "objectivity": 0.5, "objectivity_direction": 0.7}
    expr, params = build_score_sql(w)
    assert "f.political_lean" in expr
    assert "f.objectivity" in expr
    assert "ABS" in expr
    assert params["political_lean_d"] == -0.3
    assert params["objectivity_d"] == 0.7


def test_legacy_target_key_treated_as_direction():
    w = {"political_lean": 1.0, "political_lean_target": -0.5}
    expr, params = build_score_sql(w)
    assert params["political_lean_d"] == -0.5


def test_unsigned_feature_defaults_to_direction_one():
    """Backward compat: unsigned features without _direction should default
    to the catalog default (typically 1.0 = 'high is good')."""
    w = {"objectivity": 1.0}  # no objectivity_direction
    expr, params = build_score_sql(w)
    assert params["objectivity_d"] == 1.0


def test_zero_weight_feature_is_excluded():
    w = {"objectivity": 0, "info_density": 0.4}
    expr, _ = build_score_sql(w)
    assert "f.info_density" in expr
    assert "f.objectivity" not in expr


def test_threshold_creates_hard_filter():
    w = {"objectivity": 1.0, "objectivity_direction": 1.0,
         "objectivity_threshold": 0.3}
    sql, params = build_filters_sql(w)
    assert "ABS(f.objectivity - %(objectivity_d_th)s)" in sql
    assert params["objectivity_th"] == 0.3
    assert params["objectivity_d_th"] == 1.0


def test_threshold_none_no_filter():
    w = {"objectivity": 1.0, "objectivity_threshold": None}
    sql, params = build_filters_sql(w)
    assert "objectivity" not in sql
    assert "objectivity_th" not in params


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
    w = {"objectivity": 0.8, "objectivity_direction": 1.0,
         "political_lean": 1.0, "political_lean_direction": 0.0}
    out = weights_to_expression(w)
    assert "def score(article)" in out
    assert "article.objectivity" in out
    assert "article.political_lean" in out


def test_weights_to_expression_includes_threshold_filter():
    w = {"objectivity": 1.0, "objectivity_direction": 1.0,
         "objectivity_threshold": 0.5}
    out = weights_to_expression(w)
    assert "filtered by threshold" in out
    assert "abs(article.objectivity" in out


def test_parse_weights_json_invalid_returns_default():
    w = parse_weights_json("not json")
    assert isinstance(w, dict)
    assert "objectivity" in w


def test_presets_all_valid():
    for key, p in PRESETS.items():
        expr, _ = build_score_sql(p["weights"])
        assert isinstance(expr, str) and len(expr) > 0


def test_features_catalog_has_required_metadata():
    keys_seen = set()
    for feat in FEATURES:
        assert feat["key"] in FEATURE_KEYS
        assert feat["scale"] in ("signed", "unsigned")
        for k in ("label", "low", "high", "default_direction", "default_weight"):
            assert k in feat
        keys_seen.add(feat["key"])
    assert keys_seen == set(FEATURE_KEYS)


def test_resolved_weights_fills_in_missing_directions():
    w = {"objectivity": 0.5}  # nothing else
    out = resolved_weights_for_view(w)
    assert out["objectivity_direction"] == 1.0  # catalog default
    assert out["political_lean_direction"] == 0.0
    assert "recency" in out


def test_resolved_weights_upgrades_legacy_target():
    w = {"political_lean": 0.6, "political_lean_target": -0.4}
    out = resolved_weights_for_view(w)
    assert out["political_lean_direction"] == -0.4


def test_obscurity_features_in_catalog():
    keys = {f["key"] for f in FEATURES}
    assert "story_obscurity" in keys
    assert "source_obscurity" in keys


def test_obscurity_feature_in_score_sql_when_weighted():
    w = {"story_obscurity": 1.0, "source_obscurity": 0.5}
    expr, params = build_score_sql(w)
    assert "f.story_obscurity" in expr
    assert "f.source_obscurity" in expr
    assert params["story_obscurity_w"] == 1.0
    assert params["source_obscurity_w"] == 0.5


def test_paywall_feature_in_catalog():
    keys = {f["key"] for f in FEATURES}
    assert "paywall" in keys
    paywall = next(f for f in FEATURES if f["key"] == "paywall")
    assert paywall["scale"] == "unsigned"
    assert paywall["default_direction"] == 0.0
    assert paywall["default_weight"] == 0.0  # opt-in: must not perturb existing user algos


def test_paywall_in_score_sql_when_weighted():
    w = {"paywall": 1.0, "paywall_direction": 0.0}
    expr, params = build_score_sql(w)
    assert "f.paywall" in expr
    assert params["paywall_w"] == 1.0
    assert params["paywall_d"] == 0.0


def test_paywall_threshold_creates_filter():
    w = {"paywall_direction": 0.0, "paywall_threshold": 0.2}
    sql, params = build_filters_sql(w)
    assert "ABS(f.paywall - %(paywall_d_th)s)" in sql
    assert params["paywall_th"] == 0.2
