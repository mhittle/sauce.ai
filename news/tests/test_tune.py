"""Pure tests for app.tune (no Flask / no DB — runs in any env).

Parity with app.ranking.build_score_sql is the point, same as test_explain:
a nudge is driven by the scorer's own per-feature alignment factor
`1 - |value - direction| / scale`.
"""
import math

from app.tune import (
    propose_nudges,
    apply_nudges,
    sanitize_revert,
    LEARNING_RATE,
    WEIGHT_MAX,
    MIN_DELTA,
)


def test_more_like_this_boosts_aligned_feature():
    # objectivity: unsigned (scale 1), default direction 1.0; article 0.9.
    # alignment = 1 - 0.1/1 = 0.9 -> delta = LR*(2*0.9-1) = LR*0.8
    nudges = propose_nudges({"objectivity": 0.9}, {"objectivity": 1.0}, "more")
    assert len(nudges) == 1
    n = nudges[0]
    assert n["key"] == "objectivity"
    assert math.isclose(n["delta"], LEARNING_RATE * 0.8)
    assert math.isclose(n["new_weight"], 1.0 + LEARNING_RATE * 0.8)


def test_less_like_this_flips_sign():
    more = propose_nudges({"objectivity": 0.9}, {"objectivity": 1.0}, "more")[0]
    less = propose_nudges({"objectivity": 0.9}, {"objectivity": 1.0}, "less")[0]
    assert math.isclose(more["delta"], -less["delta"])
    assert less["delta"] < 0


def test_neutral_alignment_is_dropped_below_min_delta():
    # objectivity direction 1.0, article 0.5 -> alignment 0.5 -> delta 0
    assert propose_nudges({"objectivity": 0.5},
                          {"objectivity": 1.0, "objectivity_direction": 1.0},
                          "more") == []


def test_zero_weight_feature_is_never_nudged():
    # objectivity weighted, popularity not -> only objectivity is a candidate
    nudges = propose_nudges(
        {"objectivity": 0.2, "popularity": 0.9},
        {"objectivity": 1.0, "popularity": 0.0},
        "more",
    )
    assert [n["key"] for n in nudges] == ["objectivity"]


def test_missing_value_skipped():
    assert propose_nudges({}, {"objectivity": 1.0}, "more") == []


def test_clamp_to_weight_max():
    # already near the ceiling: a full +LR nudge clamps and the residual
    # move is still >= MIN_DELTA so it's reported, but new_weight == WEIGHT_MAX
    nudges = propose_nudges({"objectivity": 1.0},
                            {"objectivity": WEIGHT_MAX - 0.1}, "more")
    assert len(nudges) == 1
    assert math.isclose(nudges[0]["new_weight"], WEIGHT_MAX)
    assert math.isclose(nudges[0]["delta"], 0.1)


def test_clamp_residual_below_min_delta_dropped():
    # 0.01 of headroom -> clamped move is below MIN_DELTA -> not reported
    start = WEIGHT_MAX - 0.01
    assert propose_nudges({"objectivity": 1.0}, {"objectivity": start}, "more") == []


def test_signed_feature_uses_scale_two():
    # political_lean: signed (scale 2), default direction 0.0; article 0.5.
    # alignment = 1 - 0.5/2 = 0.75 -> delta = LR*(2*0.75-1) = LR*0.5
    nudges = propose_nudges({"political_lean": 0.5}, {"political_lean": 0.6}, "more")
    assert nudges[0]["key"] == "political_lean"
    assert math.isclose(nudges[0]["delta"], LEARNING_RATE * 0.5)


def test_top_n_and_sorted_by_abs_delta():
    weights = {"objectivity": 1.0, "info_density": 1.0, "source_reputation": 1.0}
    fv = {"objectivity": 1.0, "info_density": 0.5, "source_reputation": 0.9}
    nudges = propose_nudges(fv, weights, "more", top_n=2)
    assert len(nudges) == 2
    # objectivity (align 1.0 -> |delta| LR) ranks above source_reputation (align 0.9)
    assert nudges[0]["key"] == "objectivity"
    deltas = [abs(n["delta"]) for n in nudges]
    assert deltas == sorted(deltas, reverse=True)
    # info_density (align 0.5 -> delta 0) was dropped, not just truncated
    assert "info_density" not in {n["key"] for n in nudges}


def test_apply_nudges_only_touches_nudged_keys():
    weights = {"objectivity": 1.0, "objectivity_direction": 1.0, "recency": 0.7}
    nudges = propose_nudges({"objectivity": 0.9}, weights, "more")
    out = apply_nudges(weights, nudges)
    assert math.isclose(out["objectivity"], round(1.0 + LEARNING_RATE * 0.8, 3))
    # direction + recency + unrelated keys untouched; input not mutated
    assert out["objectivity_direction"] == 1.0
    assert out["recency"] == 0.7
    assert weights["objectivity"] == 1.0


def test_sanitize_revert_keeps_known_clamps_and_drops_junk():
    items = [
        ("objectivity", "1.5"),       # valid
        ("info_density", "9"),        # clamped to WEIGHT_MAX
        ("recency", "0.5"),           # not a FEATURE key -> dropped
        ("not_a_feature", "1.0"),     # unknown -> dropped
        ("popularity", "abc"),        # non-numeric -> dropped
    ]
    out = sanitize_revert(items, {})
    assert out == {"objectivity": 1.5, "info_density": WEIGHT_MAX}


def test_min_delta_constant_is_positive():
    assert MIN_DELTA > 0
