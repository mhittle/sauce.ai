"""Ranking: weight vector -> SQL score expression, plus presets and human-readable code.

Feature config is 3-axis per feature:
  - direction: where on the feature's scale you want articles to be
  - weight:    how much you care about it (soft contribution to score)
  - threshold: optional hard filter (`|value - direction| <= threshold`)

The on-disk shape (user_algorithms.weights_json) holds keys per feature:
  <fk>             -> weight (float)
  <fk>_direction   -> target value on the feature's scale
  <fk>_threshold   -> hard-filter distance from direction; None / missing = off

Backward compat: pre-3-axis saves used `<fk>_target` instead of `<fk>_direction`
for signed features and had no direction at all for unsigned features. The
parser / scorer accept the legacy shape and default unsigned direction to the
catalog default (typically 1.0 = "high is good").
"""
import json

# Declarative per-feature catalog. The template + ranking both read from this.
FEATURES = [
    {"key": "political_lean",        "scale": "signed",   "label": "Political lean",
     "low": "Left",         "high": "Right",     "default_direction": 0.0, "default_weight": 0.6},
    {"key": "source_lean",           "scale": "signed",   "label": "Source lean",
     "low": "Left",         "high": "Right",     "default_direction": 0.0, "default_weight": 0.4},
    {"key": "objectivity",           "scale": "unsigned", "label": "Objectivity",
     "low": "Subjective",   "high": "Objective", "default_direction": 1.0, "default_weight": 1.0},
    {"key": "reading_level",         "scale": "unsigned", "label": "Reading level",
     "low": "Easy",         "high": "Dense",     "default_direction": 0.5, "default_weight": 0.3},
    {"key": "info_density",          "scale": "unsigned", "label": "Info density",
     "low": "Sparse",       "high": "Dense",     "default_direction": 1.0, "default_weight": 0.8},
    {"key": "journalist_reputation", "scale": "unsigned", "label": "Journalist reputation",
     "low": "Lower",        "high": "Higher",    "default_direction": 1.0, "default_weight": 0.6},
    {"key": "source_reputation",     "scale": "unsigned", "label": "Source reputation",
     "low": "Lower",        "high": "Higher",    "default_direction": 1.0, "default_weight": 0.9},
    {"key": "popularity",            "scale": "unsigned", "label": "Popularity",
     "low": "Niche",        "high": "Viral",     "default_direction": 0.5, "default_weight": 0.3},
    {"key": "story_obscurity",       "scale": "unsigned", "label": "Story obscurity",
     "low": "Everywhere",   "high": "Rare",      "default_direction": 0.5, "default_weight": 0.0},
    {"key": "source_obscurity",      "scale": "unsigned", "label": "Source obscurity",
     "low": "Big outlets",  "high": "Indie",     "default_direction": 0.5, "default_weight": 0.0},
    {"key": "paywall",               "scale": "unsigned", "label": "Paywall",
     "low": "Free",         "high": "Paywalled", "default_direction": 0.0, "default_weight": 0.0},
]
FEATURES_BY_KEY = {f["key"]: f for f in FEATURES}
FEATURE_KEYS = [f["key"] for f in FEATURES]
SIGNED_FEATURES = {f["key"] for f in FEATURES if f["scale"] == "signed"}

CATEGORIES = ["politics", "world", "tech", "business", "science", "sports", "general"]


def _direction_from_weights(weights, feat):
    """Resolve the direction for a feature, accepting both `_direction` and the
    legacy `_target` key, falling back to the catalog default."""
    fk = feat["key"]
    for key in (f"{fk}_direction", f"{fk}_target"):
        if key in weights and weights[key] not in (None, ""):
            try:
                return float(weights[key])
            except (TypeError, ValueError):
                pass
    return float(feat["default_direction"])


def _threshold_from_weights(weights, feat):
    fk = feat["key"]
    v = weights.get(f"{fk}_threshold")
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _scale_width(feat):
    return 2.0 if feat["scale"] == "signed" else 1.0


PRESETS = {
    "balanced": {
        "label": "Balanced & high-quality",
        "description": "High objectivity, high info density, centrist lean, broad mix.",
        "weights": {
            "political_lean": 0.6, "political_lean_direction": 0.0,
            "source_lean": 0.4,    "source_lean_direction": 0.0,
            "objectivity": 1.0,    "objectivity_direction": 1.0,
            "reading_level": 0.3,  "reading_level_direction": 0.5,
            "info_density": 0.8,   "info_density_direction": 1.0,
            "journalist_reputation": 0.6, "journalist_reputation_direction": 1.0,
            "source_reputation": 0.9,     "source_reputation_direction": 1.0,
            "popularity": 0.3,     "popularity_direction": 0.5,
            "recency": 0.7,
        },
        "category_filter": [],
    },
    "deep_reads": {
        "label": "Deep reads",
        "description": "Long-form, analytical pieces with high reading level and density.",
        "weights": {
            "political_lean": 0.2, "political_lean_direction": 0.0,
            "source_lean": 0.2,    "source_lean_direction": 0.0,
            "objectivity": 0.6,    "objectivity_direction": 1.0,
            "reading_level": 1.0,  "reading_level_direction": 1.0,
            "info_density": 1.0,   "info_density_direction": 1.0,
            "journalist_reputation": 0.7, "journalist_reputation_direction": 1.0,
            "source_reputation": 0.8,     "source_reputation_direction": 1.0,
            "popularity": 0.1,     "popularity_direction": 0.5,
            "recency": 0.2,
        },
        "category_filter": [],
    },
    "just_the_facts": {
        "label": "Just the facts",
        "description": "Maximum objectivity, low opinion, high source reputation.",
        "weights": {
            "political_lean": 1.0, "political_lean_direction": 0.0,
            "source_lean": 0.8,    "source_lean_direction": 0.0,
            "objectivity": 1.5,    "objectivity_direction": 1.0,
            "reading_level": 0.1,  "reading_level_direction": 0.5,
            "info_density": 0.6,   "info_density_direction": 1.0,
            "journalist_reputation": 0.6, "journalist_reputation_direction": 1.0,
            "source_reputation": 1.0,     "source_reputation_direction": 1.0,
            "popularity": 0.2,     "popularity_direction": 0.5,
            "recency": 0.8,
        },
        "category_filter": [],
    },
    "local_and_world": {
        "label": "Local + world",
        "description": "Heavy on world and local news; balanced ideology.",
        "weights": {
            "political_lean": 0.5, "political_lean_direction": 0.0,
            "source_lean": 0.4,    "source_lean_direction": 0.0,
            "objectivity": 0.7,    "objectivity_direction": 1.0,
            "reading_level": 0.2,  "reading_level_direction": 0.5,
            "info_density": 0.5,   "info_density_direction": 1.0,
            "journalist_reputation": 0.4, "journalist_reputation_direction": 1.0,
            "source_reputation": 0.7,     "source_reputation_direction": 1.0,
            "popularity": 0.4,     "popularity_direction": 0.5,
            "recency": 1.0,
        },
        "category_filter": ["world", "politics", "general"],
    },
}


def default_weights():
    return PRESETS["balanced"]["weights"].copy()


def build_score_sql(weights: dict, *, jitter: float = 0.0):
    """Return (sql_expression, params_dict) computing a per-article score.

    Per feature: weight * (1 - |value - direction| / scale_width). The sum
    of feature contributions is the article's "quality" score (in [0, sum
    of weights]).

    Recency is applied as a multiplicative freshness gate on top of the
    quality score: `quality * EXP(-recency_w * hours_old / 24)`. Higher
    `recency` = steeper decay; `recency=0` disables decay entirely
    (legacy behavior). Multiplicative was chosen over additive because an
    additive recency term can't outweigh a stack of high-quality static
    features, so old high-quality articles dominated the feed forever
    (BUG-011).

    `jitter` (0..1): when >0, the final score is multiplied by
    (1 + RAND() * jitter) so consecutive refreshes shuffle articles
    within a score band (BUG-012). Default 0 keeps digest / algo preview
    / tests deterministic; only the live feed route opts in.
    """
    parts = []
    params = {}

    for feat in FEATURES:
        fk = feat["key"]
        try:
            w = float(weights.get(fk, 0) or 0)
        except (TypeError, ValueError):
            w = 0.0
        if w == 0:
            continue
        d = _direction_from_weights(weights, feat)
        scale = _scale_width(feat)
        params[f"{fk}_w"] = w
        params[f"{fk}_d"] = d
        parts.append(
            f"(%({fk}_w)s * (1 - ABS(f.{fk} - %({fk}_d)s) / {scale}))"
        )

    quality_expr = " + ".join(parts) if parts else "0"

    try:
        recency_w = float(weights.get("recency", 0) or 0)
    except (TypeError, ValueError):
        recency_w = 0.0
    if recency_w > 0:
        params["recency_w"] = recency_w
        expr = (
            f"({quality_expr}) "
            f"* EXP(-%(recency_w)s "
            f"* TIMESTAMPDIFF(MINUTE, a.published_at, UTC_TIMESTAMP()) / 1440)"
        )
    else:
        expr = quality_expr

    try:
        j = float(jitter or 0)
    except (TypeError, ValueError):
        j = 0.0
    if j > 0 and parts:
        params["jitter"] = j
        expr = f"({expr}) * (1 + RAND() * %(jitter)s)"

    return expr, params


def build_filters_sql(weights: dict):
    """Hard filters: category list, source deny, per-feature thresholds.

    A feature threshold filters out articles whose value is more than
    `threshold` away from `direction` on the feature's scale.
    """
    clauses = []
    params = {}

    for feat in FEATURES:
        fk = feat["key"]
        th = _threshold_from_weights(weights, feat)
        if th is None or th < 0:
            continue
        d = _direction_from_weights(weights, feat)
        params[f"{fk}_d_th"] = d
        params[f"{fk}_th"] = th
        clauses.append(f"ABS(f.{fk} - %({fk}_d_th)s) <= %({fk}_th)s")

    cats = weights.get("category_filter") or []
    if cats:
        placeholders = []
        for i, c in enumerate(cats):
            k = f"cat_{i}"
            placeholders.append(f"%({k})s")
            params[k] = c
        clauses.append(f"f.category IN ({', '.join(placeholders)})")
    deny = weights.get("source_deny") or []
    for i, sid in enumerate(deny):
        k = f"deny_{i}"
        params[k] = int(sid)
        clauses.append(f"a.source_id <> %({k})s")
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def weights_to_expression(weights: dict) -> str:
    """Generate a read-only Python-style snippet equivalent to the active weights."""
    parts = []
    filters = []
    for feat in FEATURES:
        fk = feat["key"]
        try:
            w = float(weights.get(fk, 0) or 0)
        except (TypeError, ValueError):
            w = 0.0
        if w != 0:
            d = _direction_from_weights(weights, feat)
            scale = _scale_width(feat)
            parts.append(f"    {w:.2f} * (1 - abs(article.{fk} - {d:.2f}) / {scale:.0f})")
        th = _threshold_from_weights(weights, feat)
        if th is not None and th >= 0:
            d = _direction_from_weights(weights, feat)
            filters.append(f"abs(article.{fk} - {d:.2f}) <= {th:.2f}")

    try:
        rec = float(weights.get("recency", 0) or 0)
    except (TypeError, ValueError):
        rec = 0.0

    cat_filter = weights.get("category_filter") or []
    deny = weights.get("source_deny") or []

    lines = ["def score(article):"]
    if filters:
        lines.append("    if not (" + " and ".join(filters) + "):")
        lines.append("        return None  # filtered by threshold")
    if not parts:
        if rec > 0:
            lines.append(f"    return 0 * exp(-{rec:.2f} * article.hours_old / 24)")
        else:
            lines.append("    return 0  # no weights set")
    else:
        lines.append("    quality = (")
        lines.append("\n      + ".join(p.strip() for p in parts))
        lines.append("    )")
        if rec > 0:
            lines.append(f"    return quality * exp(-{rec:.2f} * article.hours_old / 24)")
        else:
            lines.append("    return quality")
    lines.append("")
    if cat_filter:
        lines.append(f"# only show categories: {cat_filter}")
    if deny:
        lines.append(f"# exclude source ids: {deny}")
    lines.append("# (v1 executes this via SQL; raw Python execution comes in v2)")
    return "\n".join(lines)


def parse_weights_json(text: str) -> dict:
    try:
        d = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return default_weights()
    if not isinstance(d, dict):
        return default_weights()
    return d


def resolved_weights_for_view(weights: dict) -> dict:
    """Materialize defaults so the template can read weights[key+'_direction'] etc.

    Legacy `<fk>_target` is upgraded to `<fk>_direction`. Missing weights default
    to 0. Threshold stays None when unset (UI uses that to mean 'off')."""
    out = dict(weights)
    for feat in FEATURES:
        fk = feat["key"]
        if out.get(f"{fk}_direction") is None:
            if out.get(f"{fk}_target") is not None:
                try:
                    out[f"{fk}_direction"] = float(out[f"{fk}_target"])
                except (TypeError, ValueError):
                    out[f"{fk}_direction"] = float(feat["default_direction"])
            else:
                out[f"{fk}_direction"] = float(feat["default_direction"])
        if out.get(fk) is None:
            out[fk] = 0.0
    if out.get("recency") is None:
        out["recency"] = 0.0
    return out
