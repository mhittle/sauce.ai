"""Shareable algorithm gallery — publish, browse, adopt.

A signed-in user can publish a snapshot of their active algorithm to
`shared_algorithms`; other users browse `/gallery`, sort by usage stats,
and adopt = clone the snapshot into a NEW active row in their own
`user_algorithms`. Adoption events are logged to `algorithm_adoptions`,
which feeds the three v1 stats (total / last-7d / active). Active count
uses `user_algorithm_id IS NOT NULL` — when the adopter later deletes the
cloned profile, ON DELETE SET NULL flips that to NULL so they fall out of
the "currently in use" count automatically.

Out of scope for v1 (per roadmap): public reporting UI + an admin
moderation queue (takedowns are admin-only via DB for now).
"""
import json

from flask import (
    Blueprint, render_template, request, redirect, url_for, g, abort,
)

from ..auth import login_required
from ..db import query, execute, get_conn
from ..gallery import (
    clean_listing_name,
    clean_description,
    normalize_sort,
    sort_order_by,
    normalize_search,
    escape_like,
    snapshot_keywords,
    parse_keywords,
    SORT_KEYS,
    SORT_LABELS,
    DEFAULT_SORT,
)
from ..ranking import parse_weights_json, weights_to_expression, FEATURES

bp = Blueprint("gallery", __name__)

LIST_LIMIT = 100
MAX_PUBLISHED_PER_USER = 20


def _active_algo(user_id):
    return query(
        "SELECT id, name, weights_json FROM user_algorithms "
        "WHERE user_id = %s AND is_active = 1 "
        "ORDER BY updated_at DESC LIMIT 1",
        (user_id,), one=True,
    )


def _list_listings(sort, search, viewer_id):
    order_by = sort_order_by(sort)
    params = {}
    where = ["sa.is_public = 1"]
    if search:
        params["q"] = f"%{escape_like(search)}%"
        where.append("(sa.name LIKE %(q)s ESCAPE '\\\\' "
                     "OR sa.description LIKE %(q)s ESCAPE '\\\\')")
    where_sql = " AND ".join(where)

    params["viewer_id"] = viewer_id or 0
    sql = f"""
      SELECT
        sa.id, sa.owner_id, sa.name, sa.description, sa.weights_json,
        sa.created_at, sa.updated_at,
        (sa.owner_id = %(viewer_id)s) AS is_owner,
        COALESCE(t.total_adoptions, 0)  AS total_adoptions,
        COALESCE(t.recent_adoptions, 0) AS recent_adoptions,
        COALESCE(a.active_adoptions, 0) AS active_adoptions,
        EXISTS (
          SELECT 1 FROM algorithm_adoptions ax
          WHERE ax.shared_algorithm_id = sa.id
            AND ax.user_id = %(viewer_id)s
            AND ax.user_algorithm_id IS NOT NULL
        ) AS viewer_has_active_clone
      FROM shared_algorithms sa
      LEFT JOIN (
        SELECT shared_algorithm_id,
               COUNT(*) AS total_adoptions,
               SUM(CASE WHEN created_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
                        THEN 1 ELSE 0 END) AS recent_adoptions
        FROM algorithm_adoptions
        GROUP BY shared_algorithm_id
      ) t ON t.shared_algorithm_id = sa.id
      LEFT JOIN (
        SELECT shared_algorithm_id, COUNT(DISTINCT user_id) AS active_adoptions
        FROM algorithm_adoptions
        WHERE user_algorithm_id IS NOT NULL
        GROUP BY shared_algorithm_id
      ) a ON a.shared_algorithm_id = sa.id
      WHERE {where_sql}
      ORDER BY {order_by}
      LIMIT {LIST_LIMIT}
    """
    return query(sql, params) or []


def _weights_summary(weights_json):
    """Top three non-zero feature weights, for the listing card preview.
    Decoupled from `app.explain` (which is per-article); this is a
    static summary of the algo's emphasis."""
    try:
        w = parse_weights_json(weights_json)
    except Exception:
        return []
    entries = []
    for feat in FEATURES:
        v = float(w.get(feat["key"], 0) or 0)
        if v > 0:
            entries.append((feat["label"], v))
    entries.sort(key=lambda kv: kv[1], reverse=True)
    return entries[:3]


@bp.route("/")
def index():
    sort = normalize_sort(request.args.get("sort"))
    search = normalize_search(request.args.get("q"))
    viewer = getattr(g, "user", None)
    viewer_id = viewer["id"] if viewer else None

    listings = _list_listings(sort, search, viewer_id)
    for L in listings:
        L["weights_summary"] = _weights_summary(L["weights_json"])

    can_publish = False
    publish_default_name = ""
    if viewer:
        active = _active_algo(viewer["id"])
        can_publish = bool(active)
        publish_default_name = (active or {}).get("name") or ""

    return render_template(
        "gallery.html",
        listings=listings,
        sort=sort,
        sort_keys=SORT_KEYS,
        sort_labels=SORT_LABELS,
        search=search,
        can_publish=can_publish,
        publish_default_name=publish_default_name,
        default_sort=DEFAULT_SORT,
    )


@bp.route("/publish", methods=["POST"])
@login_required
def publish():
    """Snapshot one of the user's profiles into `shared_algorithms`.

    Source profile defaults to the active one (the gallery page's own form
    doesn't pass `algo_id`); the algo Profiles tab passes `algo_id` so a
    non-active profile can be published without first being activated."""
    uid = g.user["id"]
    try:
        algo_id = int(request.form.get("algo_id", 0) or 0)
    except (TypeError, ValueError):
        algo_id = 0
    if algo_id:
        source = query(
            "SELECT id, name, weights_json FROM user_algorithms "
            "WHERE id = %s AND user_id = %s",
            (algo_id, uid), one=True,
        )
    else:
        source = _active_algo(uid)
    if not source:
        return redirect(url_for("algo.index"))

    cap_row = query(
        "SELECT COUNT(*) AS n FROM shared_algorithms WHERE owner_id = %s",
        (uid,), one=True,
    )
    if cap_row and cap_row["n"] >= MAX_PUBLISHED_PER_USER:
        return redirect(url_for("gallery.index"))

    name = clean_listing_name(
        request.form.get("name"), fallback=source["name"] or "Untitled algorithm"
    )
    description = clean_description(request.form.get("description"))

    keyword_rows = query(
        "SELECT term, mode, weight FROM algorithm_term_prefs "
        "WHERE algorithm_id = %s ORDER BY mode, term",
        (source["id"],),
    ) or []
    keywords_json = snapshot_keywords(keyword_rows)

    execute(
        "INSERT INTO shared_algorithms "
        "(owner_id, name, description, weights_json, keywords_json) "
        "VALUES (%s, %s, %s, %s, %s)",
        (uid, name, description, source["weights_json"], keywords_json),
    )
    get_conn().commit()
    return redirect(url_for("gallery.index"))


@bp.route("/<int:lid>/adopt", methods=["POST"])
@login_required
def adopt(lid):
    uid = g.user["id"]
    listing = query(
        "SELECT id, name, weights_json, keywords_json FROM shared_algorithms "
        "WHERE id = %s AND is_public = 1",
        (lid,), one=True,
    )
    if not listing:
        abort(404)

    weights = parse_weights_json(listing["weights_json"])
    keywords = parse_keywords(listing.get("keywords_json"))
    name = (listing["name"] or "Adopted algorithm")[:120]
    # The single-active invariant every reader resolver depends on:
    # clear-all then set one. Mirrors `algo._set_active`, kept local so
    # we don't import a private helper across blueprints.
    execute(
        "UPDATE user_algorithms SET is_active = 0 WHERE user_id = %s",
        (uid,),
    )
    # Reuse a same-named profile instead of stacking a duplicate (BUG-025):
    # re-adopting "Lefty" refreshes that profile's weights + keywords rather
    # than adding another "Lefty" to the switcher.
    existing = query(
        "SELECT id FROM user_algorithms WHERE user_id = %s AND name = %s "
        "ORDER BY updated_at DESC LIMIT 1",
        (uid, name), one=True,
    )
    if existing:
        new_id = existing["id"]
        execute(
            "UPDATE user_algorithms SET weights_json=%s, expression_text=%s, is_active=1 "
            "WHERE id=%s AND user_id=%s",
            (json.dumps(weights), weights_to_expression(weights), new_id, uid),
        )
        execute(
            "DELETE FROM algorithm_term_prefs WHERE algorithm_id = %s",
            (new_id,),
        )
    else:
        new_id = execute(
            "INSERT INTO user_algorithms "
            "(user_id, name, weights_json, expression_text, is_active) "
            "VALUES (%s, %s, %s, %s, 1)",
            (uid, name, json.dumps(weights), weights_to_expression(weights)),
        )
    for kw in keywords:
        execute(
            "INSERT INTO algorithm_term_prefs "
            "(algorithm_id, term, mode, weight) "
            "VALUES (%s, %s, %s, %s)",
            (new_id, kw["term"], kw["mode"], kw["weight"]),
        )
    execute(
        "INSERT INTO algorithm_adoptions "
        "(shared_algorithm_id, user_id, user_algorithm_id) "
        "VALUES (%s, %s, %s)",
        (lid, uid, new_id),
    )
    get_conn().commit()
    return redirect(url_for("feed.index"))


@bp.route("/<int:lid>/unpublish", methods=["POST"])
@login_required
def unpublish(lid):
    """Owner-only delete. Adoption rows cascade-delete; cloned profiles
    that adopters already created are untouched (ON DELETE SET NULL on
    `algorithm_adoptions.shared_algorithm_id` is on the FK to
    shared_algorithms — once the listing is gone, the adoption rows go
    with it but the adopters' `user_algorithms` rows remain)."""
    uid = g.user["id"]
    execute(
        "DELETE FROM shared_algorithms WHERE id = %s AND owner_id = %s",
        (lid, uid),
    )
    get_conn().commit()
    return redirect(url_for("gallery.index"))
