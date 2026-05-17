"""Full-text search across articles at /search?q=...

Backed by a MySQL InnoDB FULLTEXT index on articles(title, summary)
(migration 2026-05-17-search-fulltext.sql). NATURAL LANGUAGE MODE — the
user's query is bound as a parameter, so boolean operators (+ - * ") are
treated as plain text and there is no injection surface. Results are
deduplicated by story cluster (canonical member only) and scoped by the
same source-visibility / per-user mute rules the feed uses.
"""
from flask import Blueprint, render_template, request, g

from ..db import query

bp = Blueprint("search", __name__)

PAGE_SIZE = 30
MAX_QUERY_LEN = 200


def clean_query(raw):
    """Trim, collapse internal whitespace, and cap length. Empty -> ''."""
    if not raw:
        return ""
    return " ".join(str(raw).split())[:MAX_QUERY_LEN]


def parse_page(raw):
    """1-based page number; anything unparseable or < 1 -> 1."""
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


@bp.route("/search")
def index():
    q = clean_query(request.args.get("q"))
    page = parse_page(request.args.get("page"))

    if not q:
        return render_template(
            "search.html", q=q, articles=[], page=1, has_more=False, searched=False
        )

    u = getattr(g, "user", None)
    uid = u["id"] if u else None

    vis_sql = "(s.owner_id IS NULL OR s.owner_id = %(_uid)s)" if uid else "s.owner_id IS NULL"
    pref_join_sql = ""
    pref_filter_sql = ""
    if uid:
        pref_join_sql = (
            " LEFT JOIN user_source_prefs usp "
            "ON usp.user_id = %(_uid)s AND usp.source_id = s.id"
        )
        pref_filter_sql = " AND COALESCE(usp.weight, 1.0) > 0"

    # Fetch one extra row to decide whether a "Load more" control is needed
    # without a second COUNT query.
    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.byline,
             a.published_at, a.story_id,
             s.name AS source_name,
             f.political_lean, f.category,
             MATCH (a.title, a.summary) AGAINST (%(q)s) AS relevance
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      LEFT JOIN article_features f ON f.article_id = a.id
      {pref_join_sql}
      WHERE a.status = 'classified'
        AND (a.story_id IS NULL OR a.id = a.story_id)
        AND {vis_sql}
        AND MATCH (a.title, a.summary) AGAINST (%(q)s)
        {pref_filter_sql}
      ORDER BY relevance DESC, a.published_at DESC
      LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {
        "q": q,
        "limit": PAGE_SIZE + 1,
        "offset": (page - 1) * PAGE_SIZE,
    }
    if uid:
        params["_uid"] = uid

    rows = query(sql, params)
    has_more = len(rows) > PAGE_SIZE
    articles = rows[:PAGE_SIZE]

    if request.headers.get("HX-Request"):
        return render_template(
            "partials/search_results.html",
            q=q, articles=articles, page=page, has_more=has_more,
        )
    return render_template(
        "search.html",
        q=q, articles=articles, page=page, has_more=has_more, searched=True,
    )
