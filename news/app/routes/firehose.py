"""Firehose: newest classified articles, optionally tinted by user's algorithm.

v1 implements the firehose as an HTMX polling endpoint rather than SSE — SSE
needs long-lived connections which shared cPanel hosting often kills mid-stream.
Polling at 4s gives an acceptable "live" feel and is robust on cheap hosts.
"""
from flask import Blueprint, render_template, request, g

from ..db import query
from ..firehose_cursor import firehose_cursor_clause
from ..ranking import build_score_sql, default_weights, parse_weights_json

bp = Blueprint("firehose", __name__)


def _active_weights():
    u = getattr(g, "user", None)
    if not u:
        return default_weights()
    row = query(
        "SELECT weights_json FROM user_algorithms WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
        (u["id"],), one=True,
    )
    if not row:
        return default_weights()
    return parse_weights_json(row["weights_json"])


@bp.route("/")
def index():
    weights = _active_weights()
    return render_template("firehose.html", weights=weights)


@bp.route("/stream")
def stream():
    """Newest classified articles, ordered by ``(classified_at, id)`` DESC.

    Three keyset modes (see ``firehose_cursor_clause``): no cursor →
    newest page (initial load); ``after_ts``+``after_id`` → rows strictly
    newer, prepended by the 4s poll (the live tail); ``before_ts``+
    ``before_id`` → rows strictly older, appended by "Load more". The id
    tiebreak is what makes this BUG-020-correct: ``classified_at`` is
    second-granularity and ``classify_pending`` writes same-second bursts,
    so a timestamp-only cursor silently skips rows.
    """
    weights = _active_weights()
    limit = max(1, min(int(request.args.get("limit", 25)), 100))

    score_expr, score_params = build_score_sql(weights)
    params = {**score_params, "limit": limit}

    cursor_sql, cursor_params = firehose_cursor_clause(
        request.args.get("after_ts"), request.args.get("after_id"),
        request.args.get("before_ts"), request.args.get("before_id"),
    )
    params.update(cursor_params)

    uid = (getattr(g, "user", None) or {}).get("id")
    vis_sql = "(s.owner_id IS NULL OR s.owner_id = %(_vis_owner)s)" if uid else "s.owner_id IS NULL"
    if uid:
        params["_vis_owner"] = uid

    sql = f"""
      SELECT a.id, a.title, a.url, s.name AS source_name,
             a.published_at,
             DATE_FORMAT(f.classified_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS classified_at_iso,
             f.classified_at,
             f.political_lean, f.objectivity, f.info_density,
             f.reading_level, f.source_reputation, f.popularity, f.category,
             ({score_expr}) AS score
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      WHERE a.status = 'classified' AND {vis_sql} {cursor_sql}
      ORDER BY f.classified_at DESC, a.id DESC
      LIMIT %(limit)s
    """
    rows = query(sql, params)
    return render_template("partials/firehose_rows.html", rows=rows)
