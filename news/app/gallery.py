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
"""

MAX_NAME_LEN = 120
MAX_DESCRIPTION_LEN = 500
MAX_SEARCH_LEN = MAX_NAME_LEN

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
