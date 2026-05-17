"""Cold-start interview -> a tailored weights vector.

Flask-free so it unit-tests without the app (mirrors app/algo_nl.py and
app/language.py). The route layer does the DB work; everything with
actual logic worth testing lives here.

The interview asks three things:
  - topics:  which categories to keep (hard `category_filter`); empty = all
  - balance: where on the political-lean axis to center the soft preference
  - sources: a handful of trusted outlets to boost (handled route-side via
             user_source_prefs)

Base is the `balanced` preset so the very first feed is sensible; the
interview answers are layered on top. Nothing here mutates PRESETS.
"""
from .ranking import PRESETS, CATEGORIES

# (key, label, political_lean_direction). Direction is on the signed
# -1..+1 lean axis; the soft preference (no threshold) keeps the reader
# exposed to the other side rather than walling it off.
LEAN_CHOICES = [
    {"key": "left",         "label": "Lean left",            "direction": -0.6},
    {"key": "center_left",  "label": "Slightly left",        "direction": -0.3},
    {"key": "center",       "label": "Balanced / centrist",  "direction":  0.0},
    {"key": "center_right", "label": "Slightly right",       "direction":  0.3},
    {"key": "right",        "label": "Lean right",           "direction":  0.6},
]
_LEAN_BY_KEY = {c["key"]: c for c in LEAN_CHOICES}
DEFAULT_LEAN_KEY = "center"

# Multiplier written to user_source_prefs for a picked "trusted" source.
# The feed query multiplies score by COALESCE(usp.weight, 1.0) (PR #19),
# so >1 boosts. Kept modest so it nudges rather than dominates the algo.
TRUSTED_SOURCE_WEIGHT = 1.5


def normalize_categories(values):
    """Keep only known categories, de-duplicated, in catalog order."""
    picked = {v for v in (values or []) if v in CATEGORIES}
    return [c for c in CATEGORIES if c in picked]


def lean_direction(lean_key):
    """Resolve a balance choice to its lean direction; unknown -> center."""
    return _LEAN_BY_KEY.get(lean_key, _LEAN_BY_KEY[DEFAULT_LEAN_KEY])["direction"]


def build_onboarding_weights(*, categories=None, lean_key=DEFAULT_LEAN_KEY):
    """Return a fresh weights dict: the balanced preset with the reader's
    topic filter and political-balance preference layered on.

    Pure: the returned dict is a new object; PRESETS is never mutated.
    """
    weights = dict(PRESETS["balanced"]["weights"])
    weights["political_lean_direction"] = lean_direction(lean_key)
    weights["category_filter"] = normalize_categories(categories)
    return weights


def top_trusted_sources(rows, limit=12):
    """Shape candidate source rows for the picker: one row per outlet name
    (highest reputation wins), best reputation first, capped at `limit`.

    `rows` are dicts with at least `name` and `source_reputation`.
    """
    best = {}
    for r in rows:
        name = r.get("name")
        if name is None:
            continue
        cur = best.get(name)
        if cur is None or (r.get("source_reputation") or 0) > (cur.get("source_reputation") or 0):
            best[name] = r
    ordered = sorted(
        best.values(),
        key=lambda r: (-(r.get("source_reputation") or 0), r.get("name") or ""),
    )
    return ordered[:limit]
