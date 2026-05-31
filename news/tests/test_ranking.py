from app.ranking import (
    build_score_sql, build_affinity_sql, build_filters_sql, default_weights,
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


def test_recency_clamps_future_dates():
    """BUG-026: a future published_at made TIMESTAMPDIFF negative, so the
    recency gate became EXP(positive) > 1 — an unbounded *boost* that pinned
    future-dated articles to the top of the feed. The age must be clamped at
    0 so a future date caps the multiplier at 1.0 (treated as 'now'),
    never a boost."""
    w = {"objectivity": 1.0, "recency": 0.7}
    expr, _ = build_score_sql(w)
    one_line = expr.replace("\n", " ")
    assert "GREATEST(TIMESTAMPDIFF(MINUTE, a.published_at, UTC_TIMESTAMP()), 0)" in one_line
    # the raw, un-clamped form must be gone
    assert "* TIMESTAMPDIFF(MINUTE, a.published_at, UTC_TIMESTAMP()) /" not in one_line
    # parity: the Code-tab Python equivalent clamps too
    assert "max(article.hours_old, 0)" in weights_to_expression(w)


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


def test_jitter_off_by_default():
    """BUG-012 guard: the default call must remain deterministic so the
    digest, algo preview, and tests aren't randomized."""
    w = {"objectivity": 1.0, "recency": 0.5}
    expr, params = build_score_sql(w)
    assert "RAND(" not in expr
    assert "jitter" not in params


def test_jitter_wraps_score_with_rand_multiplier():
    """BUG-012 fix: with jitter > 0 the final score is multiplied by
    (1 + RAND() * jitter) so refreshes shuffle within a score band."""
    w = {"objectivity": 1.0, "recency": 0.5}
    expr, params = build_score_sql(w, jitter=0.1)
    assert "RAND()" in expr
    assert "%(jitter)s" in expr
    assert params["jitter"] == 0.1
    # Underlying score expression is still in there.
    assert "f.objectivity" in expr
    assert "EXP(" in expr


def test_jitter_zero_disables_wrap():
    w = {"objectivity": 1.0}
    expr, params = build_score_sql(w, jitter=0)
    assert "RAND(" not in expr
    assert "jitter" not in params


def test_jitter_skipped_when_no_active_features():
    """No features weighted → no quality score → jitter on `0` is a no-op."""
    w = {"recency": 0.5}
    expr, params = build_score_sql(w, jitter=0.2)
    assert "RAND(" not in expr
    assert "jitter" not in params


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


# --- build_affinity_sql: the selection signal (BUG-029) ---------------------

def test_affinity_includes_weighted_features_with_a_keys():
    """Affinity uses distinct `_aw`/`_ad` param names so it can coexist with
    build_score_sql's `_w`/`_d` in the same query."""
    w = {"objectivity": 1.5, "info_density": 0.5}
    expr, params = build_affinity_sql(w)
    assert "f.objectivity" in expr
    assert "f.info_density" in expr
    assert "objectivity_aw" in params and "objectivity_ad" in params
    # no collision with build_score_sql's param namespace
    assert "objectivity_w" not in params


def test_affinity_weights_are_l1_normalized():
    """Weights sum to 1 so affinity is in [0,1] and comparable across algos."""
    w = {"objectivity": 1.5, "info_density": 0.5}  # total 2.0
    _, params = build_affinity_sql(w)
    assert params["objectivity_aw"] == 0.75
    assert params["info_density_aw"] == 0.25
    assert abs(sum(v for k, v in params.items() if k.endswith("_aw")) - 1.0) < 1e-9


def test_affinity_carries_no_recency_gate_or_jitter():
    """Selection must NOT be recency-gated (that's the ranking stage's job) —
    otherwise fresh articles dominate every algo's set and orthogonal algos
    converge (the BUG-029 symptom)."""
    w = {"objectivity": 1.0, "recency": 0.7}
    expr, params = build_affinity_sql(w)
    assert "EXP(" not in expr
    assert "RAND(" not in expr
    assert "recency_w" not in params


def test_affinity_empty_weights_returns_sentinel():
    """No weighted feature -> ('1', {}) so the caller can fall back to its
    default membership instead of selecting an arbitrary set."""
    assert build_affinity_sql({}) == ("1", {})
    assert build_affinity_sql({"recency": 0.7}) == ("1", {})
    assert build_affinity_sql({"objectivity": 0}) == ("1", {})


def test_affinity_uses_direction_and_scale():
    w = {"political_lean": 1.0, "political_lean_direction": -0.3}
    expr, params = build_affinity_sql(w)
    assert params["political_lean_ad"] == -0.3
    # signed feature has scale width 2
    assert "/ 2" in expr


def test_affinity_distinguishes_orthogonal_algos():
    """Two algos weighting different features produce different expressions /
    directions — the whole point of a selection stage."""
    a, _ = build_affinity_sql({"objectivity": 1.0, "objectivity_direction": 1.0})
    b, _ = build_affinity_sql({"sensationalism": 1.0, "sensationalism_direction": 1.0})
    assert "f.objectivity" in a and "f.sensationalism" not in a
    assert "f.sensationalism" in b and "f.objectivity" not in b


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


def test_country_filter_emits_in_clause():
    sql, params = build_filters_sql({"country_filter": ["US", "GB"]})
    assert "f.country IN (" in sql
    # Both codes parameterised, in order.
    assert params["country_0"] == "US"
    assert params["country_1"] == "GB"


def test_country_filter_empty_is_noop():
    sql, _ = build_filters_sql({"country_filter": []})
    assert "f.country" not in sql


def test_country_filter_combines_with_category():
    sql, params = build_filters_sql(
        {"category_filter": ["tech"], "country_filter": ["US"]})
    assert "f.category IN (" in sql
    assert "f.country IN (" in sql
    assert " AND " in sql


def test_geo_radius_emits_haversine_clause():
    w = {"geo_lat": 47.6, "geo_lng": -122.3, "geo_radius_mi": 50}
    sql, params = build_filters_sql(w)
    assert "f.geo_lat IS NOT NULL" in sql
    assert "ASIN(SQRT(" in sql
    assert params["geo_lat"] == 47.6
    assert params["geo_r"] == 50.0


def test_geo_radius_disabled_when_radius_missing_or_zero():
    """All three of lat/lng/radius must be set, and radius must be > 0."""
    assert "geo_lat" not in build_filters_sql(
        {"geo_lat": 47.6, "geo_lng": -122.3})[1]
    assert "geo_lat" not in build_filters_sql(
        {"geo_lat": 47.6, "geo_lng": -122.3, "geo_radius_mi": 0})[1]
    assert "geo_lat" not in build_filters_sql({"geo_radius_mi": 50})[1]


def test_geo_radius_handles_garbage_values():
    w = {"geo_lat": "not-a-number", "geo_lng": -122.3, "geo_radius_mi": 50}
    sql, params = build_filters_sql(w)
    assert "geo_lat" not in params
    assert "ASIN" not in sql


def test_expression_mentions_country_and_geo_filters():
    from app.ranking import weights_to_expression
    expr = weights_to_expression({
        "objectivity": 0.5,
        "country_filter": ["US", "GB"],
        "geo_lat": 47.6, "geo_lng": -122.3,
        "geo_radius_mi": 50, "geo_label": "Seattle, WA",
    })
    assert "['US', 'GB']" in expr
    assert "50 mi" in expr
    assert "Seattle, WA" in expr
PERCEPTION_KEYS = (
    "tone_calmness", "sensationalism", "analysis_depth", "emotional_charge",
    "hedging", "solution_orientation",
    "headline_length", "caps_ratio", "punctuation_intensity",
    "numeric_density", "question_headline", "quote_present",
)


def test_perception_features_all_in_catalog():
    keys = {f["key"] for f in FEATURES}
    for k in PERCEPTION_KEYS:
        assert k in keys, f"missing FEATURES entry: {k}"


def test_perception_features_are_unsigned_with_valid_metadata():
    for k in PERCEPTION_KEYS:
        feat = next(f for f in FEATURES if f["key"] == k)
        assert feat["scale"] == "unsigned"
        assert 0.0 <= feat["default_direction"] <= 1.0
        assert 0.0 <= feat["default_weight"] <= 2.0
        assert feat["label"] and feat["low"] and feat["high"]


def test_perception_feature_contributes_to_score_when_weighted():
    w = {"tone_calmness": 0.6, "tone_calmness_direction": 1.0,
         "sensationalism": 0.4, "sensationalism_direction": 0.0}
    expr, params = build_score_sql(w)
    assert "f.tone_calmness" in expr
    assert "f.sensationalism" in expr
    assert params["tone_calmness_w"] == 0.6
    assert params["sensationalism_d"] == 0.0


def test_perception_feature_threshold_filter():
    w = {"sensationalism_direction": 0.0, "sensationalism_threshold": 0.3}
    sql, params = build_filters_sql(w)
    assert "ABS(f.sensationalism - %(sensationalism_d_th)s)" in sql
    assert params["sensationalism_th"] == 0.3


def test_existing_user_algos_unaffected_when_perception_keys_missing():
    """An old user_algorithms row written before this change has none of the
    new feature keys. build_score_sql must treat missing keys as weight=0 so
    legacy scores are byte-identical to pre-deploy."""
    legacy_w = {"objectivity": 1.0, "objectivity_direction": 1.0,
                "info_density": 0.8, "info_density_direction": 1.0,
                "recency": 0.7}
    expr, params = build_score_sql(legacy_w)
    for k in PERCEPTION_KEYS:
        assert f"f.{k}" not in expr
        assert f"{k}_w" not in params
        assert f"{k}_d" not in params
