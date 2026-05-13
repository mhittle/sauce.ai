"""User-added RSS feed subscriptions.

Lets a signed-in user paste an RSS URL and add it to their personal feed
pool. The URL is validated synchronously before being persisted to
`sources` with `owner_id` set to the user. Cron `fetch_feeds` picks it up
like any other active source; per-user visibility is enforced at the
reader-feed query layer.
"""
from flask import Blueprint, render_template, request, g, redirect, url_for

from ..auth import login_required
from ..db import query, execute, get_conn
from ..feed_validation import validate_feed, infer_category

bp = Blueprint("sources", __name__)

MAX_PERSONAL_SOURCES_PER_USER = 50


@bp.route("/", methods=["GET"])
@login_required
def index():
    uid = g.user["id"]
    rows = query(
        """SELECT id, name, feed_url, homepage, category, is_active,
                  last_status, last_fetched_at, error_count
           FROM sources WHERE owner_id = %s ORDER BY id DESC""",
        (uid,),
    )
    return render_template(
        "me_sources.html", sources=rows, error=None, success=None,
        max_sources=MAX_PERSONAL_SOURCES_PER_USER,
    )


@bp.route("/", methods=["POST"])
@login_required
def add():
    uid = g.user["id"]
    url = (request.form.get("feed_url") or "").strip()
    name_override = (request.form.get("name") or "").strip()

    count_row = query(
        "SELECT COUNT(*) AS n FROM sources WHERE owner_id = %s", (uid,), one=True,
    )
    if count_row and count_row["n"] >= MAX_PERSONAL_SOURCES_PER_USER:
        return _render_with(
            error=f"You've hit the personal-source cap ({MAX_PERSONAL_SOURCES_PER_USER}). Remove one before adding another.",
        )

    existing = query("SELECT id, owner_id FROM sources WHERE feed_url = %s", (url,), one=True)
    if existing:
        if existing["owner_id"] == uid:
            return _render_with(error="You've already added this feed.")
        return _render_with(error="That feed is already in our catalog.")

    ok, info = validate_feed(url)
    if not ok:
        return _render_with(error=info)

    name = (name_override or info["name"])[:200]
    homepage = info["homepage"]
    category = infer_category(name, homepage)

    execute(
        """INSERT INTO sources
           (name, feed_url, homepage, source_lean, source_reputation,
            category, country, region, owner_id, is_active)
           VALUES (%s, %s, %s, 0, 0.5, %s, 'QA', 'national', %s, 1)""",
        (name, url, homepage, category, uid),
    )
    get_conn().commit()
    return redirect(url_for("sources.index"))


@bp.route("/<int:sid>/delete", methods=["POST"])
@login_required
def delete(sid):
    uid = g.user["id"]
    src = query("SELECT id, owner_id FROM sources WHERE id = %s", (sid,), one=True)
    if not src or src["owner_id"] != uid:
        return ("not found", 404)
    execute("DELETE FROM sources WHERE id = %s AND owner_id = %s", (sid, uid))
    get_conn().commit()
    return redirect(url_for("sources.index"))


def _render_with(error=None, success=None):
    uid = g.user["id"]
    rows = query(
        """SELECT id, name, feed_url, homepage, category, is_active,
                  last_status, last_fetched_at, error_count
           FROM sources WHERE owner_id = %s ORDER BY id DESC""",
        (uid,),
    )
    return render_template(
        "me_sources.html", sources=rows, error=error, success=success,
        max_sources=MAX_PERSONAL_SOURCES_PER_USER,
    ), (400 if error else 200)
