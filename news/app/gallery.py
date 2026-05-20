"""Shareable-algorithm gallery — pure helpers.

Flask-free / DB-free so the suite can exercise these without an app
context (same convention as `app.term_prefs` / `app.spectrum` /
`app.firehose_cursor`).

The gallery surfaces three v1 usage stats per listing:
  - **total adoptions**  — every adopt event ever (`COUNT(*)`)
  - **recent adoptions** — adopt events in the last 7 days
  - **active adoptions** — distinct users whose cloned profile still
                           exists (NULL `user_algorithm_id` = deleted)

`SORT_ORDER_BY` maps a normalized sort key to a fixed SQL ORDER BY
fragment. The map is closed (the route looks the key up by exact match)
so the caller can never inject SQL via `?sort=`.

`snapshot_keywords` / `parse_keywords` serialize the algorithm's
`algorithm_term_prefs` rows into the `shared_algorithms.keywords_json`
snapshot at publish time and re-hydrate them at adopt time, sanitized
through `term_prefs.normalize_term` / `clamp_boost` so a malformed
listing can never poison the adopter's keyword table.
"""
import json

from .term_prefs import (
    normalize_term,
    clamp_boost,
    BOOST_DEFAULT,
    VALID_MODES,
)

MAX_NAME_LEN = 120
MAX_DESCRIPTION_LEN = 500
MAX_SEARCH_LEN = MAX_NAME_LEN
MAX_KEYWORDS_IN_SNAPSHOT = 100

NAME_FALLBACK = "Untitled algorithm"

SORT_KEYS = ("popular", "trending", "active", "newest")
DEFAULT_SORT = "popular"

SORT_LABELS = {
    "popular":  "Most adopted",
    "trending": "Trending (last 7d)",
    "active":   "Currently in use",
    "newest":   "Newest",
}

SORT_ORDER_BY = {
    "popular":  "total_adoptions DESC, sa.created_at DESC, sa.id DESC",
    "trending": "recent_adoptions DESC, total_adoptions DESC, sa.created_at DESC, sa.id DESC",
    "active":   "active_adoptions DESC, total_adoptions DESC, sa.created_at DESC, sa.id DESC",
    "newest":   "sa.created_at DESC, sa.id DESC",
}


def clean_listing_name(raw, fallback=NAME_FALLBACK):
    return ((raw or "").strip()[:MAX_NAME_LEN]) or fallback


def clean_description(raw):
    return (raw or "").strip()[:MAX_DESCRIPTION_LEN]


def normalize_sort(raw):
    s = (raw or "").strip().lower()
    return s if s in SORT_ORDER_BY else DEFAULT_SORT


def sort_order_by(sort):
    return SORT_ORDER_BY[normalize_sort(sort)]


def normalize_search(raw):
    return (raw or "").strip()[:MAX_SEARCH_LEN]


def escape_like(term):
    """Same convention as `app.term_prefs.escape_like` — escape \\, %, _
    so a user-supplied search term matches literally under LIKE ESCAPE '\\\\'."""
    return (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def snapshot_keywords(rows):
    """Serialize an algorithm's `algorithm_term_prefs` rows into the JSON
    blob stored on `shared_algorithms.keywords_json`.

    Each input row is a mapping with `term`, `mode`, and (for boosts)
    `weight`. The output is a list of `{term, mode, weight}` dicts —
    normalized through `term_prefs` so a published listing never carries
    a malformed term, and capped so a runaway listing can't bloat the
    snapshot. Mute rows store `weight=BOOST_DEFAULT` for shape
    consistency (the value is ignored by the feed builder for mute).
    Returns a JSON string ready to insert."""
    out = []
    seen = set()
    for r in rows or ():
        mode = (r.get("mode") or "").lower()
        if mode not in VALID_MODES:
            continue
        term = normalize_term(r.get("term"))
        if term is None or term in seen:
            continue
        seen.add(term)
        weight = clamp_boost(r.get("weight")) if mode == "boost" else BOOST_DEFAULT
        out.append({"term": term, "mode": mode, "weight": weight})
        if len(out) >= MAX_KEYWORDS_IN_SNAPSHOT:
            break
    return json.dumps(out)


def parse_keywords(raw):
    """Re-hydrate a `shared_algorithms.keywords_json` snapshot into a
    sanitized list of keyword rows ready for INSERT into
    `algorithm_term_prefs`.

    Any malformed entry (bad mode, too-short term, non-JSON blob) is
    dropped — the snapshot is untrusted input from the publisher.
    Duplicates by term keep the first occurrence (matches the publish
    behavior). Output is capped at `MAX_KEYWORDS_IN_SNAPSHOT`."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    out = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        mode = (it.get("mode") or "").lower() if isinstance(it.get("mode"), str) else ""
        if mode not in VALID_MODES:
            continue
        term = normalize_term(it.get("term"))
        if term is None or term in seen:
            continue
        seen.add(term)
        weight = clamp_boost(it.get("weight")) if mode == "boost" else BOOST_DEFAULT
        out.append({"term": term, "mode": mode, "weight": weight})
        if len(out) >= MAX_KEYWORDS_IN_SNAPSHOT:
            break
    return out
