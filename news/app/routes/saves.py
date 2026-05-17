"""Article save / bookmark (roadmap Pri 6).

A saved article is a durable personal archive entry: jobs/maintenance.py
excludes saved articles (and their article_bodies) from the nightly
retention prune, so the reader-view copy stays readable indefinitely
even after the article would otherwise have aged out.

Toggle endpoint mirrors the signals blueprint (INSERT/DELETE, JSON).
`/saved` is the listing page in the nav.
"""
from flask import Blueprint, g, jsonify, render_template, request

from ..auth import login_required
from ..db import query, execute, get_conn

bp = Blueprint("saves", __name__)

DEFAULT_FOLDER = "Read Later"


def _require_user():
    return getattr(g, "user", None)


@bp.route("/save/<int:article_id>", methods=["POST"])
def toggle(article_id):
    u = _require_user()
    if not u:
        return jsonify({"error": "auth required"}), 401

    uid = u["id"]
    conn = get_conn()
    existing = query(
        "SELECT 1 FROM user_saves WHERE user_id = %s AND article_id = %s",
        (uid, article_id),
        one=True,
    )
    if existing:
        execute(
            "DELETE FROM user_saves WHERE user_id = %s AND article_id = %s",
            (uid, article_id),
        )
        saved = False
    else:
        folder = (request.form.get("folder") or DEFAULT_FOLDER).strip()[:64] or DEFAULT_FOLDER
        execute(
            "INSERT INTO user_saves (user_id, article_id, folder) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE folder = VALUES(folder)",
            (uid, article_id, folder),
        )
        saved = True

    conn.commit()
    return jsonify({"saved": saved})


@bp.route("/save/<int:article_id>/read", methods=["POST"])
def mark_read(article_id):
    u = _require_user()
    if not u:
        return ("", 401)
    execute(
        "UPDATE user_saves SET read_at = UTC_TIMESTAMP() "
        "WHERE user_id = %s AND article_id = %s AND read_at IS NULL",
        (u["id"], article_id),
    )
    get_conn().commit()
    return ("", 204)


@bp.route("/saved")
@login_required
def saved():
    u = g.user
    rows = query(
        """SELECT a.id, a.title, a.url, a.byline, a.published_at, a.thumbnail_url,
                  s.name AS source_name,
                  f.category, f.political_lean,
                  b.status AS body_status, b.word_count,
                  us.folder, us.saved_at, us.read_at
           FROM user_saves us
           JOIN articles a ON a.id = us.article_id
           JOIN sources s ON s.id = a.source_id
           LEFT JOIN article_features f ON f.article_id = a.id
           LEFT JOIN article_bodies b ON b.article_id = a.id
           WHERE us.user_id = %s
           ORDER BY us.saved_at DESC""",
        (u["id"],),
    )
    return render_template("saved.html", articles=rows)
