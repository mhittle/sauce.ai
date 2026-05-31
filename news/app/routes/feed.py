import datetime
import json
import os
from flask import Blueprint, render_template, request, g, redirect, url_for, jsonify, current_app, abort

from ..db import query, execute, get_conn
from ..discussion import discussions_for_articles
from ..explain import explain_article
from ..article_summary import load_bullets
from ..feed_diversify import (
    MAX_FETCH_ROWS, cap_per_source, effective_source_cap, fetch_budget,
    page_slice,
)
from ..term_prefs import build_term_clauses
from ..ranking import build_score_sql, build_filters_sql, default_weights, PRESETS, parse_weights_json
from .. import classify_topup

bp = Blueprint("feed", __name__)

SORT_OPTIONS = ("relevance", "newest", "trending")
SORT_LABELS = {
    "relevance": "Relevance",
    "newest": "Newest",
    "trending": "Trending",
}

# `popularity` was this slot's value before BUG-015 (PR #48). Alias it so
# old bookmarks, threaded category links, and the digest's URLs land on
# the trending sort instead of silently falling back to relevance.
_SORT_ALIASES = {"popularity": "trending"}


def _normalize_sort(value):
    v = (value or "").strip().lower()
    v = _SORT_ALIASES.get(v, v)
    return v if v in SORT_OPTIONS else "relevance"


def _order_by_for_sort(sort):
    if sort == "newest":
        return "ORDER BY a.published_at DESC, score DESC"
    if sort == "trending":
        # Trending heat first; the user's algo score breaks ties so within
        # the hot topics they still get their best-by-algorithm articles
        # (BUG-015). Non-trending rows tie at trending=0 and fall through
        # to the normal algo order.
        return "ORDER BY f.trending DESC, score DESC"
    return "ORDER BY score DESC, a.published_at DESC"


def _active_weights():
    """Return the active user's weights + active-algo id, or the balanced
    default for anon visitors. The id is None for anon and for signed-in
    users with no saved algorithm; callers must handle that."""
    u = getattr(g, "user", None)
    if not u:
        return default_weights(), None
    row = query(
        "SELECT id, weights_json FROM user_algorithms WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
        (u["id"],),
        one=True,
    )
    if not row:
        return default_weights(), None
    return parse_weights_json(row["weights_json"]), row["id"]


def _needs_onboarding():
    u = getattr(g, "user", None)
    if not u:
        return False
    row = query("SELECT COUNT(*) AS n FROM user_algorithms WHERE user_id = %s", (u["id"],), one=True)
    return (row["n"] if row else 0) == 0


def _maybe_signal_topup(page, page_size):
    """Demand-driven classify trigger. Two cheap COUNT(*)s + an mtime
    check + (debounced) one filesystem touch. Wrapped so any failure
    here can never break the feed response."""
    try:
        cfg = current_app.config
        override = cfg.get("CLASSIFY_TOPUP_SIGNAL_PATH") or None
        app_root = os.path.dirname(current_app.root_path)
        signal_path = classify_topup.signal_path_for(app_root, override)
        classify_topup.maybe_signal_topup(
            query, page, page_size, signal_path,
            threshold=int(cfg.get("CLASSIFY_TOPUP_THRESHOLD",
                                  classify_topup.DEFAULT_THRESHOLD)),
            cooldown_seconds=int(cfg.get("CLASSIFY_TOPUP_COOLDOWN_SECONDS",
                                         classify_topup.DEFAULT_COOLDOWN_SECONDS)),
        )
    except Exception as e:
        current_app.logger.warning("classify topup signal skipped: %s", e)


def _dedupe_switcher_rows(rows):
    """Collapse duplicate-named profiles for the header switcher so each name
    shows once. Rows arrive ordered `is_active DESC, updated_at DESC`, so the
    first row for a name is the active one (if that name is active) else the
    most-recently-updated — keep that one and drop the rest. The active id is
    computed from the full row set so it always resolves even if its name has
    duplicates. Returns (deduped_rows, active_id)."""
    active = next((r["id"] for r in rows if r["is_active"]), None)
    seen = set()
    deduped = []
    for r in rows:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        deduped.append(r)
    return deduped, active


def _switcher_profiles():
    """Profiles for the feed-header switcher. Empty for anon visitors."""
    u = getattr(g, "user", None)
    if not u:
        return [], None
    rows = query(
        "SELECT id, name, is_active FROM user_algorithms WHERE user_id = %s "
        "ORDER BY is_active DESC, updated_at DESC",
        (u["id"],),
    ) or []
    return _dedupe_switcher_rows(rows)


@bp.route("/")
def index():
    if _needs_onboarding():
        return redirect(url_for("algo.onboarding"))
    weights, active_algo_id = _active_weights()
    page = max(1, int(request.args.get("page", 1)))
    page_size = 40
    category = (request.args.get("category") or "").strip() or None
    sort = _normalize_sort(request.args.get("sort"))
    order_by_sql = _order_by_for_sort(sort)

    jitter = float(current_app.config.get("FEED_JITTER", 0.0) or 0.0)
    score_expr, score_params = build_score_sql(weights, jitter=jitter)
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

        # Per-algorithm keywords for the currently active profile (managed
        # on /algo's Keywords tab). The builder dedupes terms and lets mute
        # win over boost.
        term_rows = []
        if active_algo_id:
            term_rows = query(
                "SELECT term, mode, weight FROM algorithm_term_prefs "
                "WHERE algorithm_id = %s",
                (active_algo_id,),
            ) or []
        term_mute_sql, term_boost_expr, term_params = build_term_clauses(term_rows)
        if term_boost_expr:
            term_boost_mult = f" * ({term_boost_expr})"

    uid = u["id"] if u else None
    vis_sql = "(s.owner_id IS NULL OR s.owner_id = %(_vis_owner)s)" if uid else "s.owner_id IS NULL"
    vis_params = {"_vis_owner": uid} if uid else {}

    # Dedup: `a.id = a.story_id` keeps only canonical members. Each cluster's
    # canonical was chosen at classify time by max(source_reputation), tiebreak
    # oldest published_at. `cluster_size` rides in the row for future UI use
    # (Across-the-spectrum in-feed badge, story dossier).
    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.thumbnail_url, a.byline,
             a.published_at, a.story_id,
             s.name AS source_name, s.id AS source_id,
             f.political_lean, f.source_lean, f.objectivity, f.reading_level,
             f.info_density, f.journalist_reputation, f.source_reputation,
             f.popularity, f.trending, f.category, f.country,
             COALESCE(cs.cluster_size, 1) AS cluster_size,
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
        {cat_filter_sql}
        {pref_filter_sql}
        {term_mute_sql}
        {down_filter_sql}
      {order_by_sql}
      LIMIT %(limit)s OFFSET %(offset)s
    """
    # BUG-021: over-fetch from the top so the per-source cap (applied in
    # Python below) still yields a full page. Single-source-burst pages
    # would otherwise be silently short. The active profile's unique-sources
    # toggle (if set) tightens that cap to 1 for this viewer.
    default_cap = int(current_app.config.get("FEED_MAX_PER_SOURCE", 0) or 0)
    src_cap = effective_source_cap(weights, default_cap)
    fetch_limit = min(fetch_budget(page, page_size, src_cap), MAX_FETCH_ROWS)
    params = {**score_params, **filter_params, **pref_params, **vis_params,
              **term_params,
              "limit": fetch_limit, "offset": 0}
    raw = query(sql, params)
    capped = cap_per_source(raw, cap=src_cap)
    articles = page_slice(capped, page, page_size)

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

        saved_rows = query(
            f"SELECT article_id FROM user_saves "
            f"WHERE user_id = %s AND article_id IN ({placeholders})",
            (u["id"], *ids),
        )
        saved_ids = {r["article_id"] for r in saved_rows}
        for a in articles:
            a["saved"] = a["id"] in saved_ids
    else:
        for a in articles:
            a["thumb"] = None
            a["saved"] = False

    if articles:
        disc = discussions_for_articles([a["id"] for a in articles])
        for a in articles:
            a["discussions"] = disc.get(a["id"], [])

    _maybe_signal_topup(page, page_size)

    if request.headers.get("HX-Request"):
        return render_template(
            "partials/feed_cards.html",
            articles=articles, page=page, weights=weights, category=category,
            sort=sort,
        )

    cat_rows = query(f"""
        SELECT f.category, COUNT(*) AS n
        FROM article_features f
        JOIN articles a ON a.id = f.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE a.status = 'classified'
          AND a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
          AND f.category IS NOT NULL AND f.category <> ''
          AND {vis_sql}
        GROUP BY f.category ORDER BY n DESC
    """, vis_params)
    profiles, active_algo_id = _switcher_profiles()
    return render_template(
        "feed.html",
        articles=articles, page=page, weights=weights,
        categories=cat_rows, active_category=category,
        sort=sort, sort_options=SORT_OPTIONS, sort_labels=SORT_LABELS,
        profiles=profiles, active_algo_id=active_algo_id,
    )


@bp.route("/click/<int:article_id>", methods=["POST"])
def click(article_id):
    u = getattr(g, "user", None)
    uid = u["id"] if u else None
    execute("INSERT INTO user_clicks (user_id, article_id) VALUES (%s, %s)", (uid, article_id))
    get_conn().commit()
    return ("", 204)


@bp.route("/article/<int:article_id>/explain")
def explain(article_id):
    """Why-this-article panel: the score breakdown for *this* viewer.

    Lazily fetched by HTMX when the "Why?" toggle on a card is clicked, so
    the feed query stays cheap. Uses the same active-weights resolution and
    source-visibility scoping as the feed itself (anon → balanced default),
    so the explanation reflects what actually ranked the row for the viewer.
    """
    weights = _active_weights()
    u = getattr(g, "user", None)
    uid = u["id"] if u else None
    vis_sql = "(s.owner_id IS NULL OR s.owner_id = %(_vis_owner)s)" if uid else "s.owner_id IS NULL"
    vis_params = {"_vis_owner": uid} if uid else {}

    row = query(
        f"""
        SELECT a.id, a.title, a.published_at,
               f.political_lean, f.source_lean, f.objectivity, f.reading_level,
               f.info_density, f.journalist_reputation, f.source_reputation,
               f.popularity, f.trending, f.story_obscurity, f.source_obscurity,
               f.paywall
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        JOIN article_features f ON f.article_id = a.id
        WHERE a.id = %(aid)s AND a.status = 'classified' AND {vis_sql}
        """,
        {"aid": article_id, **vis_params},
        one=True,
    )
    if not row:
        abort(404)

    hours_old = None
    if row.get("published_at"):
        delta = datetime.datetime.utcnow() - row["published_at"]
        hours_old = max(0.0, delta.total_seconds() / 3600.0)

    ex = explain_article(row, weights, hours_old=hours_old, top_n=3)
    return render_template("partials/why_panel.html", a=row, ex=ex)


@bp.route("/article/<int:article_id>/summary")
def summary(article_id):
    """3-bullet TL;DR panel, lazily fetched by HTMX when the "TL;DR" toggle on
    a card is clicked, so the feed query stays cheap. Degrades to an empty
    panel when no summary exists (ungated article, body not extracted, or the
    article_summaries migration not yet applied)."""
    bullets = load_bullets(article_id)
    return render_template("partials/summary_panel.html", bullets=bullets)
