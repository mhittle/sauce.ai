import json
from flask import Blueprint, render_template, request, g, redirect, url_for, jsonify

from ..db import query, execute, get_conn
from ..ranking import build_score_sql, build_filters_sql, default_weights, PRESETS, parse_weights_json

bp = Blueprint("feed", __name__)


def _active_weights():
    """Return the active user's weights, or the balanced default for anon visitors."""
    u = getattr(g, "user", None)
    if not u:
        return default_weights()
    row = query(
        "SELECT weights_json FROM user_algorithms WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
        (u["id"],),
        one=True,
    )
    if not row:
        return default_weights()
    return parse_weights_json(row["weights_json"])


def _needs_onboarding():
    u = getattr(g, "user", None)
    if not u:
        return False
    row = query("SELECT COUNT(*) AS n FROM user_algorithms WHERE user_id = %s", (u["id"],), one=True)
    return (row["n"] if row else 0) == 0


@bp.route("/")
def index():
    if _needs_onboarding():
        return redirect(url_for("algo.onboarding"))
    weights = _active_weights()
    page = max(1, int(request.args.get("page", 1)))
    page_size = 30
    category = (request.args.get("category") or "").strip() or None

    score_expr, score_params = build_score_sql(weights)
    filter_sql, filter_params = build_filters_sql(weights)

    cat_filter_sql = ""
    if category:
        filter_params["category_tab"] = category
        cat_filter_sql = " AND f.category = %(category_tab)s"

    u = getattr(g, "user", None)
    pref_join_sql = ""
    pref_filter_sql = ""
    pref_score_mult = ""
    pref_params = {}
    if u:
        pref_join_sql = (
            " LEFT JOIN user_source_prefs usp "
            "ON usp.user_id = %(_pref_uid)s AND usp.source_id = s.id"
        )
        pref_filter_sql = " AND COALESCE(usp.weight, 1.0) > 0"
        pref_score_mult = " * COALESCE(usp.weight, 1.0)"
        pref_params["_pref_uid"] = u["id"]

    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.thumbnail_url, a.byline,
             a.published_at, s.name AS source_name, s.id AS source_id,
             f.political_lean, f.source_lean, f.objectivity, f.reading_level,
             f.info_density, f.journalist_reputation, f.source_reputation,
             f.popularity, f.category, f.country,
             ({score_expr}){pref_score_mult} AS score
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      {pref_join_sql}
      WHERE a.status = 'classified'
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        {filter_sql}
        {cat_filter_sql}
        {pref_filter_sql}
      ORDER BY score DESC, a.published_at DESC
      LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {**score_params, **filter_params, **pref_params,
              "limit": page_size, "offset": (page - 1) * page_size}
    articles = query(sql, params)

    if u and articles:
        ids = [a["id"] for a in articles]
        placeholders = ",".join(["%s"] * len(ids))
        thumb_rows = query(
            f"SELECT article_id, signal_type FROM user_signals "
            f"WHERE user_id = %s AND signal_type IN ('thumb_up','thumb_down') "
            f"AND article_id IN ({placeholders})",
            (u["id"], *ids),
        )
        by_id = {r["article_id"]: r["signal_type"] for r in thumb_rows}
        for a in articles:
            a["thumb"] = by_id.get(a["id"])
    else:
        for a in articles:
            a["thumb"] = None

    if request.headers.get("HX-Request"):
        return render_template(
            "partials/feed_cards.html",
            articles=articles, page=page, weights=weights, category=category,
        )

    cat_rows = query("""
        SELECT f.category, COUNT(*) AS n
        FROM article_features f
        JOIN articles a ON a.id = f.article_id
        WHERE a.status = 'classified'
          AND a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
          AND f.category IS NOT NULL AND f.category <> ''
        GROUP BY f.category ORDER BY n DESC
    """)
    return render_template(
        "feed.html",
        articles=articles, page=page, weights=weights,
        categories=cat_rows, active_category=category,
    )


@bp.route("/click/<int:article_id>", methods=["POST"])
def click(article_id):
    u = getattr(g, "user", None)
    uid = u["id"] if u else None
    execute("INSERT INTO user_clicks (user_id, article_id) VALUES (%s, %s)", (uid, article_id))
    get_conn().commit()
    return ("", 204)
