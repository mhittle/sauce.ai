"""Ranking: weight vector -> SQL score expression, plus presets and human-readable code."""
import json

# All numeric features the user can weight. Keep keys in sync with feature_catalog.
FEATURE_KEYS = [
    "political_lean",        # signed_scale -1..1
    "source_lean",           # signed_scale -1..1
    "objectivity",
    "reading_level",
    "info_density",
    "journalist_reputation",
    "source_reputation",
    "popularity",
]

# For signed_scale features the algorithm carries both a weight and a target
# (e.g. "I want pieces close to lean = -0.2"). For unsigned features only a weight.
SIGNED_FEATURES = {"political_lean", "source_lean"}

CATEGORIES = ["politics", "world", "tech", "business", "science", "sports", "general"]

PRESETS = {
    "balanced": {
        "label": "Balanced & high-quality",
        "description": "High objectivity, high info density, centrist lean, broad mix.",
        "weights": {
            "political_lean": 0.6, "political_lean_target": 0.0,
            "source_lean": 0.4,    "source_lean_target": 0.0,
            "objectivity": 1.0,
            "reading_level": 0.3,
            "info_density": 0.8,
            "journalist_reputation": 0.6,
            "source_reputation": 0.9,
            "popularity": 0.3,
            "recency": 0.7,
        },
        "category_filter": [],
    },
    "deep_reads": {
        "label": "Deep reads",
        "description": "Long-form, analytical pieces with high reading level and density.",
        "weights": {
            "political_lean": 0.2, "political_lean_target": 0.0,
            "source_lean": 0.2,    "source_lean_target": 0.0,
            "objectivity": 0.6,
            "reading_level": 1.0,
            "info_density": 1.0,
            "journalist_reputation": 0.7,
            "source_reputation": 0.8,
            "popularity": 0.1,
            "recency": 0.2,
        },
        "category_filter": [],
    },
    "just_the_facts": {
        "label": "Just the facts",
        "description": "Maximum objectivity, low opinion, high source reputation.",
        "weights": {
            "political_lean": 1.0, "political_lean_target": 0.0,
            "source_lean": 0.8,    "source_lean_target": 0.0,
            "objectivity": 1.5,
            "reading_level": 0.1,
            "info_density": 0.6,
            "journalist_reputation": 0.6,
            "source_reputation": 1.0,
            "popularity": 0.2,
            "recency": 0.8,
        },
        "category_filter": [],
    },
    "local_and_world": {
        "label": "Local + world",
        "description": "Heavy on world and local news; balanced ideology.",
        "weights": {
            "political_lean": 0.5, "political_lean_target": 0.0,
            "source_lean": 0.4,    "source_lean_target": 0.0,
            "objectivity": 0.7,
            "reading_level": 0.2,
            "info_density": 0.5,
            "journalist_reputation": 0.4,
            "source_reputation": 0.7,
            "popularity": 0.4,
            "recency": 1.0,
        },
        "category_filter": ["world", "politics", "general"],
    },
}


def default_weights():
    return PRESETS["balanced"]["weights"].copy()


def build_score_sql(weights: dict):
    """Return (sql_expression, params_dict) computing a score from article_features columns.

    Recency uses an exponential decay on hours since publish:
      recency = EXP( -hours_since_published / 24 )

    For signed features we score `1 - |value - target|` so values near the target get max score.
    For unsigned features we score the value directly.
    """
    parts = []
    params = {}

    def w(key, default=0.0):
        try:
            return float(weights.get(key, default))
        except (TypeError, ValueError):
            return default

    for fk in FEATURE_KEYS:
        weight = w(fk, 0.0)
        if weight == 0:
            continue
        if fk in SIGNED_FEATURES:
            target = w(f"{fk}_target", 0.0)
            params[f"{fk}_w"] = weight
            params[f"{fk}_t"] = target
            parts.append(f"(%({fk}_w)s * (1 - ABS(f.{fk} - %({fk}_t)s)/2))")
        else:
            params[f"{fk}_w"] = weight
            parts.append(f"(%({fk}_w)s * f.{fk})")

    recency_w = w("recency", 0.0)
    if recency_w != 0:
        params["recency_w"] = recency_w
        parts.append("(%(recency_w)s * EXP(-TIMESTAMPDIFF(MINUTE, a.published_at, UTC_TIMESTAMP())/1440))")

    expr = " + ".join(parts) if parts else "0"
    return expr, params


def build_filters_sql(weights: dict):
    """Optional hard filters: category list, source allow/deny, lean band."""
    clauses = []
    params = {}
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
    for fk in FEATURE_KEYS:
        wv = float(weights.get(fk, 0) or 0)
        if wv == 0:
            continue
        if fk in SIGNED_FEATURES:
            t = float(weights.get(f"{fk}_target", 0) or 0)
            parts.append(f"    {wv:.2f} * (1 - abs(article.{fk} - {t:.2f}) / 2)")
        else:
            parts.append(f"    {wv:.2f} * article.{fk}")
    rec = float(weights.get("recency", 0) or 0)
    if rec != 0:
        parts.append(f"    {rec:.2f} * exp(-article.hours_old / 24)")
    cat_filter = weights.get("category_filter") or []
    deny = weights.get("source_deny") or []

    lines = ["def score(article):"]
    if not parts:
        lines.append("    return 0  # no weights set")
    else:
        lines.append("    return (")
        lines.append("\n      + ".join(p.strip() for p in parts))
        lines.append("    )")
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
