"""Why This Article: per-feature breakdown of an article's ranking score.

The pure, Flask-free / DB-free core behind the "Why?" popover on a feed
card (mirrors the helper convention of `spectrum.py` / `trending.py` /
`firehose_cursor.py`). Given an article's `article_features` row and the
viewer's active algorithm weights it reproduces, in Python, exactly the
per-feature term `app.ranking.build_score_sql` evaluates in SQL —
`weight * (1 - |value - direction| / scale)` — plus the multiplicative
recency gate, so the explanation always matches what actually ranked the
article for that user.

Parity is load-bearing: `_direction_from_weights` and `_scale_width` are
imported from `app.ranking` rather than re-derived so a future change to
direction/scale resolution can't silently desync the explainer from the
scorer. The per-user source multiplier (`user_source_prefs`) and the
per-algorithm keyword boost (`algorithm_term_prefs`) feed.py applies
*outside* the feature sum are deliberately not modeled here — this panel
explains feature contributions and recency, which is what the roadmap
item asks for.
"""
import math

from .ranking import FEATURES, _direction_from_weights, _scale_width


def feature_contributions(feature_values, weights):
    """Per-weighted-feature contribution, highest first.

    Each entry: key, label, value, direction, weight, scale, contribution.
    Features with weight 0 are skipped (excluded from the SQL sum too); a
    missing / non-numeric value is skipped because a NULL feature value
    nulls that term in SQL — there is nothing to explain for it.
    """
    out = []
    for feat in FEATURES:
        fk = feat["key"]
        try:
            w = float(weights.get(fk, 0) or 0)
        except (TypeError, ValueError):
            w = 0.0
        if w == 0:
            continue
        raw = feature_values.get(fk)
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        d = _direction_from_weights(weights, feat)
        scale = _scale_width(feat)
        contribution = w * (1.0 - abs(v - d) / scale)
        out.append({
            "key": fk,
            "label": feat["label"],
            "value": v,
            "direction": d,
            "weight": w,
            "scale": scale,
            "contribution": contribution,
        })
    out.sort(key=lambda c: c["contribution"], reverse=True)
    return out


def recency_multiplier(weights, hours_old):
    """(recency_weight, multiplier) mirroring build_score_sql's freshness gate.

    multiplier is None when recency is disabled (weight <= 0) or the age is
    unknown — the caller then treats the quality sum as the final score
    (legacy / recency=0 behavior)."""
    try:
        rec = float(weights.get("recency", 0) or 0)
    except (TypeError, ValueError):
        rec = 0.0
    if rec <= 0 or hours_old is None or hours_old < 0:
        return rec, None
    return rec, math.exp(-rec * hours_old / 24.0)


def explain_article(feature_values, weights, *, hours_old=None, top_n=3):
    """Full explanation payload for the Why panel.

    `top` is the `top_n` strongest positive contributors (what the roadmap
    item surfaces); `contributions` is the complete ranked list for the
    "show all" expansion.
    """
    contribs = feature_contributions(feature_values, weights)
    quality = sum(c["contribution"] for c in contribs)
    rec_w, mult = recency_multiplier(weights, hours_old)
    final = quality if mult is None else quality * mult
    return {
        "contributions": contribs,
        "top": contribs[:top_n],
        "quality": quality,
        "recency_weight": rec_w,
        "recency_multiplier": mult,
        "hours_old": hours_old,
        "final_score": final,
    }
