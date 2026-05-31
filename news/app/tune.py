"""Tune from this article: article-anchored weight nudges with a preview.

The pure, Flask-free / DB-free core behind the "More / less like this"
control on a feed card. It is the *suggest* wedge of the larger Signal
Learning item (roadmap, Pri 8): instead of silently learning, it computes
how it would nudge the viewer's active algorithm weights so the feed
shows more (or fewer) articles like this one, and the route surfaces that
vector for accept / undo before anything persists.

Parity with the scorer is load-bearing, exactly as in `app.explain`:
`_direction_from_weights` and `_scale_width` are imported from
`app.ranking` rather than re-derived, and the per-feature *alignment*
`1 - |value - direction| / scale` is the same factor
`build_score_sql` multiplies each weight by. So a nudge is expressed in
the scorer's own units and can later be absorbed into the full Signal
Learning regression without a second adjustment representation — the
nudge mutates the existing `user_algorithms.weights_json`, the same store
the regression will write to (no separate adjustment-vector table, per
the roadmap note).

Only features the algorithm already weights (weight > 0) are nudged:
introducing a brand-new feature the user never chose would be a
surprising side effect of a single click. Directions, thresholds, and
filters are never touched — this lever moves how *much* the reader cares
about features the article is (mis)aligned on, not what they target.
"""

from .ranking import FEATURES_BY_KEY, FEATURE_KEYS, _direction_from_weights, _scale_width

# How hard a single click pushes a weight, in the scorer's weight units
# (the /algo sliders run 0..2). A perfectly-aligned feature moves by a full
# LEARNING_RATE on "more like this"; a perfectly-misaligned one by the same
# amount in the opposite direction; a neutral feature (alignment 0.5) doesn't
# move. "Less like this" flips the sign.
LEARNING_RATE = 0.25

# The /algo weight slider bounds. Keep a nudge inside the range the manual
# editor allows so the two stay interchangeable.
WEIGHT_MIN = 0.0
WEIGHT_MAX = 2.0

# Don't surface (or apply) a nudge smaller than this after clamping — it
# would be noise the reader can't perceive and clutters the panel.
MIN_DELTA = 0.05

# How many nudges the preview panel shows, strongest first.
TOP_N = 5

DIRECTIONS = ("more", "less")


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _alignment(value, direction, scale):
    """The per-unit-weight contribution factor `1 - |v - d| / scale`,
    clamped to [0, 1]. 1.0 = the article sits exactly on the target; 0.0 =
    as far from the target as the scale allows."""
    return _clamp(1.0 - abs(value - direction) / scale, 0.0, 1.0)


def propose_nudges(feature_values, weights, direction, *, top_n=TOP_N):
    """Propose per-feature weight nudges for `more` / `less` like this.

    For each currently-weighted feature with a numeric value on the
    article, compute `delta = sign * LEARNING_RATE * (2*alignment - 1)`
    (sign +1 for "more", -1 for "less"), apply it to the current weight,
    clamp to [WEIGHT_MIN, WEIGHT_MAX], and keep the move only if it changes
    the weight by at least MIN_DELTA after clamping. Returns the strongest
    `top_n` moves (by absolute delta), each a dict:
    key, label, value, direction (target), alignment, current_weight,
    delta, new_weight.

    Pure: no rounding of the stored weight here beyond float math; the
    route rounds on persist and the template rounds for display.
    """
    sign = 1.0 if direction == "more" else -1.0
    out = []
    for fk in FEATURE_KEYS:
        feat = FEATURES_BY_KEY[fk]
        try:
            w = float(weights.get(fk, 0) or 0)
        except (TypeError, ValueError):
            w = 0.0
        if w <= 0:
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
        align = _alignment(v, d, scale)
        delta = sign * LEARNING_RATE * (2.0 * align - 1.0)
        new_w = _clamp(w + delta, WEIGHT_MIN, WEIGHT_MAX)
        actual = new_w - w
        if abs(actual) < MIN_DELTA:
            continue
        out.append({
            "key": fk,
            "label": feat["label"],
            "value": v,
            "direction": d,
            "alignment": align,
            "current_weight": w,
            "delta": actual,
            "new_weight": new_w,
        })
    out.sort(key=lambda n: abs(n["delta"]), reverse=True)
    return out[:top_n]


def apply_nudges(weights, nudges, *, ndigits=3):
    """Return a copy of `weights` with each nudge's feature weight set to its
    `new_weight` (rounded to keep weights_json tidy). Pure — only the nudged
    feature-weight keys change; directions / thresholds / filters are
    untouched."""
    out = dict(weights)
    for n in nudges:
        out[n["key"]] = round(float(n["new_weight"]), ndigits)
    return out


def sanitize_revert(items, weights):
    """Build a {feature_key: clamped_weight} map from untrusted (key, value)
    pairs for the Undo path.

    The prior weights ride back through the form, so re-validate: keep only
    real feature keys and coerce each value to a float clamped into the
    editor's [WEIGHT_MIN, WEIGHT_MAX] range. Used to merge the pre-nudge
    weights back onto whatever the active profile currently holds.
    `weights` is accepted for symmetry / future use but the result is the
    sanitized override map the caller merges in.
    """
    out = {}
    for key, value in items:
        if key not in FEATURE_KEYS:
            continue
        try:
            w = float(value)
        except (TypeError, ValueError):
            continue
        out[key] = _clamp(w, WEIGHT_MIN, WEIGHT_MAX)
    return out
