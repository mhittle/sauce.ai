"""News Near You — `/local`: the user's algorithm, filtered to a place.

Reuses the existing geo filter that already ships inside
`ranking.build_filters_sql` (`_geo_filter_from_weights` -> `haversine_sql`).
We do **not** rewrite ranking — we copy the viewer's active weights,
inject the page-chosen `{geo_lat, geo_lng, geo_radius_mi}` over the top,
and run the same scoring + filtering + diversification path the home feed
runs. So local news inherits keyword prefs, downvote-hide, jitter, paging,
and per-source caps for free, and can never desync from `/`.

Where the place comes from is pure-Python in `app/geo_local.py`. This
module is the thin Flask layer on top.

Scope discipline (mirrors BUG-021 / `spectrum.py`): `/`, `/firehose`,
`/search`, `/saved`, and the digest are **untouched**. This blueprint
keeps its own query so the freshly-merged BUG-030 split between
`affinity` (selection) and `score` (ranking) in `feed.index()` can land
without coupling to a refactor of that route. The composition here is
intentionally the same shape as `feed.index()`'s — if a future PR
extracts a shared `_run_feed_query()` helper, this route can collapse
onto it cleanly.

NOT BUG-007 class: reads only columns already on prod
(`article_features.geo_*`). No migration, no cron, no env var, no new
dependency. Anonymous-safe (balanced defaults + cookie).
"""
from __future__ import annotations

from flask import (
    Blueprint, current_app, g, make_response, render_template, request,
    url_for,
)

from ..db import query
from ..discussion import discussions_for_articles
from ..feed_diversify import (
    MAX_FETCH_ROWS, cap_per_source, effective_source_cap, page_slice,
    rank_for_display,
)
from ..geo import geocode_query
from ..geo_local import (
    COOKIE_MAX_AGE, COOKIE_NAME,
    inject_geo_into_weights, resolve_local_place, serialize_cookie,
)
from ..ranking import (
    GEO_RADIUS_DEFAULT_MI, GEO_RADIUS_MAX_MI,
    build_affinity_sql, build_filters_sql, build_score_sql, default_weights,
    parse_weights_json,
)
from ..term_prefs import build_term_clauses

bp = Blueprint("local", __name__)

PAGE_SIZE = 40

# Radius choices for the dropdown. Capped at GEO_RADIUS_MAX_MI; values
# above are dropped so the picker never offers a setting the SQL would
# silently clamp.
_RADIUS_CHOICES = (10, 25, 50, 100, 200, 500)


def _active_weights_and_algo():
    u = getattr(g, "user", None)
    if not u:
        return default_weights(), None
    row = query(
        "SELECT id, weights_json FROM user_algorithms "
        "WHERE user_id = %s AND is_active = 1 "
        "ORDER BY updated_at DESC LIMIT 1",
        (u["id"],), one=True,
    )
    if not row:
        return default_weights(), None
    return parse_weights_json(row["weights_json"]), row["id"]


def _radius_options(current: float) -> list[dict]:
    """Stable, deduped radius dropdown that always includes the current
    value (so a cookie-set radius like 75 stays visible even if it's not
    in the canned list)."""
    seen = set()
    out = []
    for r in _RADIUS_CHOICES:
        if r > GEO_RADIUS_MAX_MI:
            continue
        if r in seen:
            continue
        seen.add(r)
        out.append({"value": r, "selected": int(round(current)) == int(r)})
    cur = int(round(current))
    if cur not in seen and 0 < cur <= GEO_RADIUS_MAX_MI:
        out.append({"value": cur, "selected": True})
        out.sort(key=lambda d: d["value"])
    return out


def _run_local_query(weights, *, page, page_size):
    """Same shape as feed.index()'s query, with `category` and `sort`
    pinned (local is relevance-sorted; categories aren't surfaced here
    yet). Keeping a parallel copy avoids touching feed.py while BUG-030
    is freshly merged — see module docstring.
    """
    jitter = float(current_app.config.get("FEED_JITTER", 0.0) or 0.0)
    affinity_expr, affinity_params = build_affinity_sql(weights)
    score_expr, score_params = build_score_sql(weights, jitter=jitter)
    filter_sql, filter_params = build_filters_sql(weights)

    u = getattr(g, "user", None)
    pref_join_sql = ""
    pref_filter_sql = ""
    pref_score_mult = ""
    pref_params = {}
    term_mute_sql = ""
    term_boost_mult = ""
    term_params = {}
    down_filter_sql = ""
    if u:
        down_filter_sql = (
            " AND a.id NOT IN (SELECT article_id FROM user_signals "
            "WHERE user_id = %(_dv_uid)s AND signal_type = 'thumb_down')"
        )
        pref_params["_dv_uid"] = u["id"]
        pref_join_sql = (
            " LEFT JOIN user_source_prefs usp "
            "ON usp.user_id = %(_pref_uid)s AND usp.source_id = s.id"
        )
        pref_filter_sql = " AND COALESCE(usp.weight, 1.0) > 0"
        pref_score_mult = " * COALESCE(usp.weight, 1.0)"
        pref_params["_pref_uid"] = u["id"]

        term_rows = []
        algo_id = getattr(g, "_local_active_algo_id", None)
        if algo_id:
            term_rows = query(
                "SELECT term, mode, weight FROM algorithm_term_prefs "
                "WHERE algorithm_id = %s",
                (algo_id,),
            ) or []
        term_mute_sql, term_boost_expr, term_params = build_term_clauses(term_rows)
        if term_boost_expr:
            term_boost_mult = f" * ({term_boost_expr})"

    uid = u["id"] if u else None
    vis_sql = "(s.owner_id IS NULL OR s.owner_id = %(_vis_owner)s)" if uid else "s.owner_id IS NULL"
    vis_params = {"_vis_owner": uid} if uid else {}

    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.thumbnail_url, a.byline,
             a.published_at, a.story_id,
             s.name AS source_name, s.id AS source_id,
             f.political_lean, f.source_lean, f.objectivity, f.reading_level,
             f.info_density, f.journalist_reputation, f.source_reputation,
             f.popularity, f.trending, f.category, f.country,
             f.geo_place,
             COALESCE(cs.cluster_size, 1) AS cluster_size,
             ({affinity_expr}){pref_score_mult}{term_boost_mult} AS affinity,
             ({score_expr}){pref_score_mult}{term_boost_mult} AS score
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      LEFT JOIN (
        SELECT story_id, COUNT(*) AS cluster_size
        FROM articles
        WHERE status = 'classified'
          AND published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        GROUP BY story_id
      ) cs ON cs.story_id = a.story_id
      {pref_join_sql}
      WHERE a.status = 'classified'
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        AND (a.story_id IS NULL OR a.id = a.story_id)
        AND {vis_sql}
        {filter_sql}
        {pref_filter_sql}
        {term_mute_sql}
        {down_filter_sql}
      ORDER BY affinity DESC, a.published_at DESC
      LIMIT %(selpool)s
    """
    sel_pool = min(
        int(current_app.config.get("FEED_SELECTION_POOL", 600) or 600),
        MAX_FETCH_ROWS,
    )
    default_cap = int(current_app.config.get("FEED_MAX_PER_SOURCE", 0) or 0)
    src_cap = effective_source_cap(weights, default_cap)
    params = {**affinity_params, **score_params, **filter_params,
              **pref_params, **vis_params, **term_params,
              "selpool": sel_pool}
    selected = query(sql, params)
    capped = cap_per_source(selected, cap=src_cap)
    return page_slice(rank_for_display(capped, "relevance"), page, page_size)


def _enrich(articles):
    """Per-row thumb / saved / discussion enrichment (same as feed.index)."""
    u = getattr(g, "user", None)
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
        saved_rows = query(
            f"SELECT article_id FROM user_saves "
            f"WHERE user_id = %s AND article_id IN ({placeholders})",
            (u["id"], *ids),
        )
        saved_ids = {r["article_id"] for r in saved_rows}
        for a in articles:
            a["thumb"] = by_id.get(a["id"])
            a["saved"] = a["id"] in saved_ids
    else:
        for a in articles:
            a["thumb"] = None
            a["saved"] = False

    if articles:
        disc = discussions_for_articles([a["id"] for a in articles])
        for a in articles:
            a["discussions"] = disc.get(a["id"], [])


@bp.route("/local")
def index():
    weights, active_algo_id = _active_weights_and_algo()
    g._local_active_algo_id = active_algo_id

    place_param = request.args.get("place")
    radius_param = request.args.get("radius")
    cookie_value = request.cookies.get(COOKIE_NAME)
    place, persist = resolve_local_place(
        place_param, radius_param, cookie_value, weights,
        default_radius=float(GEO_RADIUS_DEFAULT_MI),
        max_radius=float(GEO_RADIUS_MAX_MI),
        geocode=geocode_query,
    )

    page = max(1, int(request.args.get("page", 1)))

    # Pre-resolve a friendly "couldn't find that place" flag for the
    # template — a non-empty ?place= that didn't geocode and didn't fall
    # back to anything is the empty-state-with-error path.
    unresolved = bool((place_param or "").strip()) and place is None

    articles = []
    if place is not None:
        local_weights = inject_geo_into_weights(weights, place)
        articles = _run_local_query(
            local_weights, page=page, page_size=PAGE_SIZE,
        )
        _enrich(articles)

    # Load-more URL preserves the URL-level state (place / radius) so the
    # cookie can't drift from the visible page during a paging session.
    load_more_url = None
    if place is not None:
        load_more_url = url_for(
            "local.index",
            page=page + 1,
            place=place.get("label") or None,
            radius=int(round(place["radius"])),
        )

    if request.headers.get("HX-Request"):
        return render_template(
            "partials/feed_cards.html",
            articles=articles, page=page,
            weights=weights, category=None, sort="relevance",
            load_more_url=load_more_url,
        )

    resp = make_response(render_template(
        "local.html",
        articles=articles, page=page,
        place=place, unresolved=unresolved,
        place_query=place_param or "",
        radius_options=_radius_options(
            place["radius"] if place else float(GEO_RADIUS_DEFAULT_MI)
        ),
        radius_default=int(GEO_RADIUS_DEFAULT_MI),
        radius_max=int(GEO_RADIUS_MAX_MI),
        load_more_url=load_more_url,
    ))
    if persist and place is not None:
        resp.set_cookie(
            COOKIE_NAME,
            serialize_cookie(place),
            max_age=COOKIE_MAX_AGE,
            path="/",
            samesite="Lax",
            secure=request.is_secure,
            httponly=False,
        )
    return resp
