import datetime
import json
import os
from flask import Blueprint, render_template, request, g, redirect, url_for, jsonify, current_app, abort

from ..db import query, execute, get_conn
from ..discussion import discussions_for_articles
from ..explain import explain_article
from ..article_summary import load_bullets
from ..feed_diversify import (
    MAX_FETCH_ROWS, cap_per_source, effective_source_cap, page_slice,
    rank_for_display,
)
from ..term_prefs import build_term_clauses
from ..ranking import (
    build_affinity_sql, build_score_sql, build_filters_sql, default_weights,
    PRESETS, parse_weights_json, weights_to_expression, FEATURE_KEYS,
)
from ..tune import propose_nudges, apply_nudges, sanitize_revert, DIRECTIONS
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

    # BUG-030: weights drive *selection* (which articles are in the list),
    # the sort drives *ranking* (the order they're shown). `affinity` is the
    # recency-free, weight-normalized feature match used to pick the candidate
    # SET; `score` is the recency-gated relevance signal used to order it.
    jitter = float(current_app.config.get("FEED_JITTER", 0.0) or 0.0)
    affinity_expr, affinity_params = build_affinity_sql(weights)
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
        {cat_filter_sql}
        {pref_filter_sql}
        {term_mute_sql}
        {down_filter_sql}
      ORDER BY affinity DESC, a.published_at DESC
      LIMIT %(selpool)s
    """
    # BUG-030: select the top-N most-affine articles as the membership SET
    # (what's *in* the list). Fixed per request (not page-scaled) so paging
    # walks a stable set; clamped at MAX_FETCH_ROWS. The per-source cap then
    # trims the set for diversity (keeping each source's most-affine rows,
    # since the SQL returns them affinity-ordered); the active profile's
    # unique-sources toggle tightens that cap to 1. Finally rank_for_display
    # re-orders the capped set by the user's sort (ranking != selection).
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
    articles = page_slice(rank_for_display(capped, sort), page, page_size)

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
    weights, _ = _active_weights()
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


def _tune_target(uid):
    """Active profile (id, name, weights) for a signed-in user. A reader who
    reached the feed always has an active row (feed._needs_onboarding sends
    those with none to onboarding), but fall back to defaults defensively."""
    row = query(
        "SELECT id, name, weights_json FROM user_algorithms "
        "WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
        (uid,), one=True,
    )
    if not row:
        return None, None, default_weights()
    return row["id"], row["name"], parse_weights_json(row["weights_json"])


def _article_feature_row(article_id, uid):
    """All feature columns for one classified article, scoped to sources the
    user may see (global + their own). Returns None if not found / not
    visible. Selects every FEATURE_KEYS column so a nudge can touch any
    weighted feature, not just the subset the Why panel explains."""
    cols = ", ".join(f"f.{k}" for k in FEATURE_KEYS)
    row = query(
        f"""
        SELECT a.id, a.title, {cols}
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        JOIN article_features f ON f.article_id = a.id
        WHERE a.id = %(aid)s AND a.status = 'classified'
          AND (s.owner_id IS NULL OR s.owner_id = %(_vo)s)
        """,
        {"aid": article_id, "_vo": uid}, one=True,
    )
    return row


def _persist_weights(algo_id, uid, weights):
    execute(
        "UPDATE user_algorithms SET weights_json=%s, expression_text=%s "
        "WHERE id=%s AND user_id=%s",
        (json.dumps(weights), weights_to_expression(weights), algo_id, uid),
    )
    get_conn().commit()


@bp.route("/article/<int:article_id>/tune")
def tune(article_id):
    """Preview the weight nudges a "more / less like this" click would make,
    without persisting anything. Signed-in only — the control is hidden for
    anon visitors, who have no algorithm to tune."""
    u = getattr(g, "user", None)
    if not u:
        abort(401)
    direction = (request.args.get("dir") or "").strip().lower()
    if direction not in DIRECTIONS:
        abort(400)
    _, name, weights = _tune_target(u["id"])
    row = _article_feature_row(article_id, u["id"])
    if not row:
        abort(404)
    nudges = propose_nudges(row, weights, direction)
    return render_template(
        "partials/tune_panel.html",
        a=row, direction=direction, nudges=nudges, profile_name=name,
    )


@bp.route("/article/<int:article_id>/tune", methods=["POST"])
def tune_apply(article_id):
    """Recompute the nudges server-side (never trust the previewed deltas)
    and persist them onto the viewer's active profile's weights_json."""
    u = getattr(g, "user", None)
    if not u:
        abort(401)
    direction = (request.form.get("dir") or "").strip().lower()
    if direction not in DIRECTIONS:
        abort(400)
    algo_id, name, weights = _tune_target(u["id"])
    row = _article_feature_row(article_id, u["id"])
    if not row:
        abort(404)
    if not algo_id:
        return render_template(
            "partials/tune_applied.html",
            a=row, applied=[], prev={}, profile_name=None, no_profile=True,
        )
    nudges = propose_nudges(row, weights, direction)
    prev = {}
    if nudges:
        prev = {n["key"]: round(float(weights.get(n["key"], 0) or 0), 3) for n in nudges}
        _persist_weights(algo_id, u["id"], apply_nudges(weights, nudges))
    return render_template(
        "partials/tune_applied.html",
        a=row, applied=nudges, prev=prev, profile_name=name, no_profile=False,
    )


@bp.route("/article/<int:article_id>/tune/undo", methods=["POST"])
def tune_undo(article_id):
    """Revert a just-applied nudge: merge the pre-nudge feature weights (sent
    back as `prev_<feature>` fields, re-validated server-side) onto whatever
    the active profile currently holds."""
    u = getattr(g, "user", None)
    if not u:
        abort(401)
    algo_id, _, weights = _tune_target(u["id"])
    items = [
        (field[len("prev_"):], value)
        for field, value in request.form.items()
        if field.startswith("prev_")
    ]
    override = sanitize_revert(items, weights)
    if algo_id and override:
        merged = dict(weights)
        merged.update(override)
        _persist_weights(algo_id, u["id"], merged)
    return render_template("partials/tune_reverted.html", a={"id": article_id})
