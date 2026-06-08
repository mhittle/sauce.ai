from app.signals.scoring import (default_rule, is_flagged, score_project,
                                 why_flagged)


def test_score_blends_bool_number_and_category_weights():
    values = {
        "is_commercial": True,
        "cabinet_relevance": 1.0,
        "value_tier": "large",
        "distress_stalled": True,
        "distress_stalled_absent": False,
    }
    weights = {
        "is_commercial": 2.0,
        "cabinet_relevance": 4.0,
        "value_tier": {"mid": 1.0, "large": 2.0},
        "distress_stalled": 2.5,
    }
    # 2 + 4*1.0 + 2 + 2.5 = 10.5
    assert score_project(values, weights) == 10.5


def test_missing_signal_contributes_zero():
    assert score_project({}, {"is_commercial": 5.0}) == 0.0


def test_numeric_normalizer_recency():
    # fresh (0 days) -> full weight; stale (90 days) -> ~0
    assert score_project({"fresh_recency_days": 0}, {"fresh_recency_days": 1.0}) == 1.0
    assert score_project({"fresh_recency_days": 90}, {"fresh_recency_days": 1.0}) == 0.0


def test_is_flagged_threshold():
    assert is_flagged(6.0, 6.0) is True
    assert is_flagged(5.9, 6.0) is False


def test_why_flagged_sorted_desc():
    rule = default_rule()
    values = {"cabinet_relevance": 1.0, "is_commercial": True,
              "geo_shippable": True}
    rows = why_flagged(values, rule["weights"])
    assert rows[0]["signal"] == "cabinet_relevance"
    assert all(rows[i]["contribution"] >= rows[i + 1]["contribution"]
               for i in range(len(rows) - 1))


def test_default_rule_shape():
    rule = default_rule()
    assert "weights" in rule and "threshold" in rule
    assert rule["weights"]["cabinet_relevance"] > 0
