"""Composite lead scoring (PRD §8 lead_score, §9 scored rules).

A Rule carries `weights` ({signal_id: weight}) and a `threshold`. The score
is a weighted blend of the project's signal values; projects scoring at/above
the threshold are flagged "Call Today". Pure functions — no DB.

A weight may be:
  * a number  — applied to a bool (1/0) or a normalized numeric contribution,
                or to mere presence of a category/text value;
  * a dict    — {category_value: weight} for category signals (e.g. value_tier).
"""
from __future__ import annotations

from typing import Union

Weight = Union[float, int, dict]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# Map a numeric signal to a 0..1 contribution before applying its weight.
NUMERIC_NORMALIZERS = {
    "cabinet_relevance": lambda v: _clamp01(v),
    "fresh_recency_days": lambda v: _clamp01(1 - v / 90.0),
    "distance_mi": lambda v: _clamp01(1 - v / 500.0),
    "repeat_gc_count": lambda v: _clamp01(v / 5.0),
}


def _contribution(signal_id: str, value, weight: Weight) -> float:
    if value is None:
        return 0.0
    if isinstance(weight, dict):
        return float(weight.get(str(value), 0))
    w = float(weight)
    if isinstance(value, bool):
        return w if value else 0.0
    if isinstance(value, (int, float)):
        norm = NUMERIC_NORMALIZERS.get(signal_id)
        return w * (norm(value) if norm else _clamp01(float(value)))
    return w  # presence of a category/text value


def score_project(signal_values: dict, weights: dict) -> float:
    total = 0.0
    for signal_id, weight in weights.items():
        total += _contribution(signal_id, signal_values.get(signal_id), weight)
    return round(total, 3)


def is_flagged(score: float, threshold: float) -> bool:
    return score >= threshold


def why_flagged(signal_values: dict, weights: dict, limit: int = 6) -> list[dict]:
    """Ranked contributions for the project-detail 'why flagged' panel."""
    rows = []
    for signal_id, weight in weights.items():
        contrib = _contribution(signal_id, signal_values.get(signal_id), weight)
        if contrib:
            rows.append({"signal": signal_id,
                         "value": signal_values.get(signal_id),
                         "contribution": round(contrib, 3)})
    rows.sort(key=lambda r: r["contribution"], reverse=True)
    return rows[:limit]


def default_rule() -> dict:
    """A sensible starter profile: distressed commercial cabinet work, nearby."""
    return {
        "name": "Distressed commercial cabinet leads",
        "profile": "default",
        "threshold": 6.0,
        "weights": {
            "is_commercial": 2.0,
            "cabinet_relevance": 4.0,
            "value_tier": {"mid": 1.0, "large": 2.0, "mega": 3.0},
            "distress_stalled": 2.5,
            "distress_expiring": 2.0,
            "distress_stopwork": 2.5,
            "distress_renewal": 1.5,
            "distress_inspections": 1.5,
            "new_gc": 1.0,
            "geo_shippable": 1.5,
            "fresh_recency_days": 1.0,
        },
    }
