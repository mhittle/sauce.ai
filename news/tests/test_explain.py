"""Pure tests for app.explain (no Flask / no DB — runs in any env).

The point of this module is parity with app.ranking.build_score_sql: a
contribution must equal `weight * (1 - |value - direction| / scale)` and
recency must be the same `exp(-w * hours/24)` multiplicative gate.
"""
import math

from app.explain import (
    feature_contributions,
    recency_multiplier,
    explain_article,
)


def test_unsigned_feature_formula():
    # objectivity: unsigned (scale 1), catalog default direction 1.0
    out = feature_contributions({"objectivity": 0.87}, {"objectivity": 1.0})
    assert len(out) == 1
    c = out[0]
    assert c["key"] == "objectivity"
    assert c["scale"] == 1.0
    assert c["direction"] == 1.0
    assert math.isclose(c["contribution"], 1.0 * (1 - abs(0.87 - 1.0) / 1.0))


def test_signed_feature_uses_scale_two():
    # political_lean: signed (scale 2), default direction 0.0
    out = feature_contributions({"political_lean": 0.5}, {"political_lean": 0.6})
    c = out[0]
    assert c["scale"] == 2.0
    assert math.isclose(c["contribution"], 0.6 * (1 - abs(0.5 - 0.0) / 2.0))


def test_explicit_direction_respected():
    out = feature_contributions(
        {"political_lean": -0.3},
        {"political_lean": 1.0, "political_lean_direction": -0.3},
    )
    assert math.isclose(out[0]["contribution"], 1.0)  # perfect match


def test_legacy_target_key_treated_as_direction():
    """Parity with ranking._direction_from_weights legacy support."""
    out = feature_contributions(
        {"political_lean": -0.5},
        {"political_lean": 1.0, "political_lean_target": -0.5},
    )
    assert math.isclose(out[0]["contribution"], 1.0)


def test_sorted_by_contribution_desc():
    fv = {"objectivity": 1.0, "info_density": 0.2, "source_reputation": 0.6}
    w = {"objectivity": 1.0, "info_density": 1.0, "source_reputation": 1.0}
    out = feature_contributions(fv, w)
    vals = [c["contribution"] for c in out]
    assert vals == sorted(vals, reverse=True)
    assert out[0]["key"] == "objectivity"  # perfect match to default dir 1.0


def test_zero_weight_excluded():
    out = feature_contributions(
        {"objectivity": 0.9, "info_density": 0.9},
        {"objectivity": 0, "info_density": 0.5},
    )
    keys = [c["key"] for c in out]
    assert keys == ["info_density"]


def test_missing_or_none_value_skipped():
    out = feature_contributions({"objectivity": None}, {"objectivity": 1.0})
    assert out == []
    out2 = feature_contributions({}, {"info_density": 1.0})
    assert out2 == []


def test_non_numeric_value_skipped():
    out = feature_contributions({"objectivity": "n/a"}, {"objectivity": 1.0})
    assert out == []


def test_non_numeric_weight_treated_as_zero():
    out = feature_contributions({"objectivity": 0.9}, {"objectivity": "lots"})
    assert out == []


def test_recency_disabled_returns_none_multiplier():
    w, mult = recency_multiplier({"recency": 0}, 12.0)
    assert w == 0.0
    assert mult is None


def test_recency_none_hours_returns_none_multiplier():
    _, mult = recency_multiplier({"recency": 0.7}, None)
    assert mult is None


def test_recency_multiplier_matches_exp_gate():
    w, mult = recency_multiplier({"recency": 0.7}, 24.0)
    assert w == 0.7
    assert math.isclose(mult, math.exp(-0.7 * 24.0 / 24.0))


def test_negative_hours_treated_as_unknown():
    _, mult = recency_multiplier({"recency": 0.7}, -3.0)
    assert mult is None


def test_explain_article_aggregates_and_applies_recency():
    fv = {"objectivity": 1.0, "info_density": 1.0}
    w = {"objectivity": 1.0, "info_density": 0.5, "recency": 0.7}
    ex = explain_article(fv, w, hours_old=24.0, top_n=3)
    # both perfect matches: quality = 1.0 + 0.5
    assert math.isclose(ex["quality"], 1.5)
    assert math.isclose(ex["recency_multiplier"], math.exp(-0.7))
    assert math.isclose(ex["final_score"], 1.5 * math.exp(-0.7))
    assert len(ex["top"]) == 2


def test_explain_article_no_recency_final_equals_quality():
    ex = explain_article({"objectivity": 0.8}, {"objectivity": 1.0}, hours_old=10.0)
    assert ex["recency_multiplier"] is None
    assert math.isclose(ex["final_score"], ex["quality"])


def test_top_n_respected():
    fv = {"objectivity": 1.0, "info_density": 0.9, "source_reputation": 0.8,
          "reading_level": 0.5}
    w = {"objectivity": 1.0, "info_density": 1.0, "source_reputation": 1.0,
         "reading_level": 1.0}
    ex = explain_article(fv, w, top_n=2)
    assert len(ex["top"]) == 2
    assert len(ex["contributions"]) == 4
    # top is the prefix of the fully ranked list
    assert ex["top"] == ex["contributions"][:2]


def test_empty_weights_yield_zero_score():
    ex = explain_article({"objectivity": 0.9}, {})
    assert ex["contributions"] == []
    assert ex["quality"] == 0
    assert ex["final_score"] == 0
