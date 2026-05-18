"""Per-user keyword mute & boost management.

A signed-in user keeps two disjoint term lists. `mute` drops any article
whose title+summary contains the term; `boost` multiplies a matching
article's score by the term's weight. Both are applied at the reader-feed
query layer (see `app/term_prefs.py` + `routes/feed.py`); this blueprint
is just the CRUD surface at `/terms`.
"""
from flask import Blueprint, render_template, request, g, redirect, url_for

from ..auth import login_required
from ..db import query, execute, get_conn
from ..term_prefs import normalize_term, clamp_boost, BOOST_DEFAULT, VALID_MODES

bp = Blueprint("term_prefs", __name__)

MAX_TERMS_PER_USER = 100


def _load(uid):
    rows = query(
        "SELECT id, term, mode, weight, created_at "
        "FROM user_term_prefs WHERE user_id = %s ORDER BY mode, term",
        (uid,),
    )
    return (
        [r for r in rows if r["mode"] == "mute"],
        [r for r in rows if r["mode"] == "boost"],
    )


def _render(error=None, success=None, status=200):
    muted, boosted = _load(g.user["id"])
    body = render_template(
        "me_terms.html",
        muted=muted, boosted=boosted, error=error, success=success,
        max_terms=MAX_TERMS_PER_USER, boost_default=BOOST_DEFAULT,
    )
    return body if status == 200 else (body, status)


@bp.route("/", methods=["GET"])
@login_required
def index():
    return _render()


@bp.route("/", methods=["POST"])
@login_required
def add():
    uid = g.user["id"]
    mode = (request.form.get("mode") or "").strip().lower()
    if mode not in VALID_MODES:
        return _render(error="Pick mute or boost.", status=400)

    term = normalize_term(request.form.get("term"))
    if term is None:
        return _render(
            error="Enter a keyword or phrase (at least 2 characters).",
            status=400,
        )

    weight = clamp_boost(request.form.get("weight")) if mode == "boost" else BOOST_DEFAULT

    count_row = query(
        "SELECT COUNT(*) AS n FROM user_term_prefs WHERE user_id = %s",
        (uid,), one=True,
    )
    existing = query(
        "SELECT id FROM user_term_prefs WHERE user_id = %s AND term = %s",
        (uid, term), one=True,
    )
    if not existing and count_row and count_row["n"] >= MAX_TERMS_PER_USER:
        return _render(
            error=f"You've hit the keyword cap ({MAX_TERMS_PER_USER}). "
                  f"Remove one before adding another.",
            status=400,
        )

    # A term has exactly one mode per user; re-adding it in the other
    # mode just moves it (keeps the mute/boost lists disjoint).
    execute(
        "INSERT INTO user_term_prefs (user_id, term, mode, weight) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE mode = VALUES(mode), weight = VALUES(weight)",
        (uid, term, mode, weight),
    )
    get_conn().commit()
    return redirect(url_for("term_prefs.index"))


@bp.route("/<int:tid>/delete", methods=["POST"])
@login_required
def delete(tid):
    uid = g.user["id"]
    execute(
        "DELETE FROM user_term_prefs WHERE id = %s AND user_id = %s",
        (tid, uid),
    )
    get_conn().commit()
    return redirect(url_for("term_prefs.index"))
