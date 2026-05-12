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

    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.thumbnail_url, a.byline,
             a.published_at, s.name AS source_name, s.id AS source_id,
             f.political_lean, f.source_lean, f.objectivity, f.reading_level,
             f.info_density, f.journalist_reputation, f.source_reputation,
             f.popularity, f.category, f.country,
             ({score_expr}) AS score
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      WHERE a.status = 'classified'
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        {filter_sql}
        {cat_filter_sql}
      ORDER BY score DESC, a.published_at DESC
      LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {**score_params, **filter_params, "limit": page_size, "offset": (page - 1) * page_size}
    articles = query(sql, params)

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
