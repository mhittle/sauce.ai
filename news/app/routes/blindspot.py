"""Blindspot — the biggest stories your algorithm is hiding from you.

The "category of one" feature: invert the reader's own algorithm to
surface the high-coverage stories the live home feed would systematically
suppress, naming the responsible knob (mute / hard filter / low
relevance) and showing the cross-spectrum coverage so the reader can
decide whether to retune.

Honesty contract: a Blindspot is genuinely "what `/` would not show this
user" — we never invent a parallel definition. The selected-set check
reuses `feed._selected_story_ids`, which composes the same building
blocks as `feed.index()` (affinity + filters + mutes + visibility +
downvote). The hard-filter check re-runs `ranking.build_filters_sql`
exactly (and source-pref + downvote predicates) against the same
canonical-member rows. The mute check uses `term_prefs.normalize_term`
to mirror the SQL builder's case-insensitive substring semantics so the
in-Python check can't drift.

NOT BUG-007 class: reads only columns/tables already on prod. No
migration, no cron, no env var required (knobs default), no new
dependency.

Failure mode: any exception in the page body falls through to a
"couldn't compute your blindspots right now" panel — never a 500.
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, render_template

from ..blindspot import classify_blindspots, reason_label
from ..db import query
from ..ranking import (
    build_filters_sql, default_weights, parse_weights_json,
)
from .feed import _selected_story_ids
from .story import _fetch_cluster, _lead_paragraph, _lean_bucket
from ..spectrum import pick_spectrum_sample
from ..term_prefs import normalize_term

bp = Blueprint("blindspot", __name__)

# Hard cap on the candidate set pulled from the outlet-burst query. The
# `(story_id, published_at)` index supports the group scan; we still
# clamp so a freak burst-day (election night) can't pull thousands of
# rows. Anything above this is statistically irrelevant — we then narrow
# to `BLINDSPOT_MAX_ITEMS` after classification.
CANDIDATE_CAP = 200

# Selection-pool cap for the "what would the feed show" check. Larger
# than the live feed's default so a thin algorithm at the high-pool
# end still sees its true selection; clamped at MAX_FETCH_ROWS by the
# helper itself.
SELECT_POOL = 600

# Sibling articles shown in each blindspot's spectrum strip.
SPECTRUM_PEEK_LIMIT = 3


def _active_weights_and_algo():
    """Return (weights, active_algo_id) for the signed-in viewer, or
    (None, None) for anon / signed-in-with-no-saved-algorithm. The
    Blindspot UI shows an onboarding state in those branches — defaults
    would invert into garbage."""
    u = getattr(g, "user", None)
    if not u:
        return None, None
    row = query(
        "SELECT id, weights_json FROM user_algorithms "
        "WHERE user_id = %s AND is_active = 1 "
        "ORDER BY updated_at DESC LIMIT 1",
        (u["id"],), one=True,
    )
    if not row:
        return None, None
    return parse_weights_json(row["weights_json"]), row["id"]


def _big_stories(window_hours, min_outlets, limit):
    """Outlet-burst candidates over the window — the "world is covering
    this hard" universe. Mirrors `jobs/breaking_alerts._candidate_query`
    (global outlets, distinct-source count) plus a `LIMIT` so the result
    is bounded."""
    sql = """
      SELECT a.story_id,
             COUNT(DISTINCT a.source_id) AS outlet_count,
             MAX(a.published_at)         AS latest
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      WHERE a.story_id IS NOT NULL
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %(window)s HOUR
        AND s.owner_id IS NULL
        AND a.status = 'classified'
      GROUP BY a.story_id
      HAVING outlet_count >= %(min_outlets)s
      ORDER BY outlet_count DESC
      LIMIT %(lim)s
    """
    rows = query(sql, {
        "window": int(window_hours),
        "min_outlets": int(min_outlets),
        "lim": int(limit),
    }) or []
    return rows


def _canonical_meta(story_ids):
    """Title + summary for each candidate's canonical article. Used by the
    in-Python mute check (mirrors `term_prefs._MATCH_EXPR`) and by the
    UI headline. Returns `{story_id: {"title", "summary"}}`."""
    if not story_ids:
        return {}
    placeholders = ",".join(["%s"] * len(story_ids))
    rows = query(
        f"SELECT id, title, summary FROM articles "
        f"WHERE id IN ({placeholders}) AND status = 'classified'",
        tuple(story_ids),
    ) or []
    return {r["id"]: {"title": r["title"], "summary": r.get("summary") or ""}
            for r in rows}


def _mute_terms_for(algo_id):
    """Active profile's mute terms, normalized the same way the SQL
    builder normalizes them — so the in-Python substring check can't
    drift from the live mute clauses on `/`. Returns a list of lowercased
    trimmed terms (empty / short ones dropped)."""
    if not algo_id:
        return []
    rows = query(
        "SELECT term FROM algorithm_term_prefs "
        "WHERE algorithm_id = %s AND mode = 'mute'",
        (algo_id,),
    ) or []
    out = []
    for r in rows:
        t = normalize_term(r["term"])
        if t:
            out.append(t)
    return out


def _mute_hit(meta, mute_terms):
    """If any normalized mute term is a substring of the canonical
    title+summary (lowercased), return the first matching term. Mirrors
    `term_prefs._MATCH_EXPR` (case-insensitive LIKE on title+summary)."""
    if not mute_terms:
        return None
    haystack = (meta["title"] or "")
    if meta.get("summary"):
        haystack = haystack + " " + meta["summary"]
    haystack = haystack.lower()
    for t in mute_terms:
        if t in haystack:
            return t
    return None


def _filter_survivors(weights, story_ids):
    """Story_ids that survive the active profile's hard filters + source
    prefs + downvote — the same predicates `feed.index()` applies (minus
    the affinity ORDER / sel-pool LIMIT). A candidate not in the result
    set was excluded by a hard knob.

    Empty input → empty result. We re-build the filter SQL via
    `build_filters_sql` so a future filter addition (category, country,
    geo, source-deny, per-feature threshold) is picked up automatically.
    """
    if not story_ids:
        return set()

    filter_sql, filter_params = build_filters_sql(weights)

    u = getattr(g, "user", None)
    pref_join_sql = ""
    pref_filter_sql = ""
    pref_params = {}
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
        pref_params["_pref_uid"] = u["id"]

    uid = u["id"] if u else None
    vis_sql = (
        "(s.owner_id IS NULL OR s.owner_id = %(_vis_owner)s)" if uid
        else "s.owner_id IS NULL"
    )
    vis_params = {"_vis_owner": uid} if uid else {}

    id_keys = []
    id_params = {}
    for i, sid in enumerate(story_ids):
        k = f"_bs_id_{i}"
        id_keys.append(f"%({k})s")
        id_params[k] = sid

    sql = f"""
      SELECT a.story_id
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      {pref_join_sql}
      WHERE a.status = 'classified'
        AND a.id = a.story_id
        AND a.story_id IN ({','.join(id_keys)})
        AND {vis_sql}
        {filter_sql}
        {pref_filter_sql}
        {down_filter_sql}
    """
    params = {**filter_params, **pref_params, **vis_params, **id_params}
    rows = query(sql, params) or []
    return {r["story_id"] for r in rows if r.get("story_id") is not None}


def _spectrum_for(story_id):
    """Cross-spectrum coverage strip for one blindspot. Returns a small
    sample of sibling articles (one per source, round-robin L/C/R) plus
    the total other-member count for the dossier link. None on failure
    so the card can render without a strip rather than 500."""
    try:
        members = _fetch_cluster(story_id)
    except Exception:
        return None
    if not members:
        return None
    sample = pick_spectrum_sample(members, exclude_id=story_id,
                                  limit=SPECTRUM_PEEK_LIMIT)
    for m in sample:
        m["lead"] = _lead_paragraph(m.get("body_text"), m.get("summary"))
        m["bucket"] = _lean_bucket(m.get("political_lean"))
    canonical = next((m for m in members if m["id"] == story_id), None)
    return {
        "members": members,
        "sample": sample,
        "total_others": max(0, len(members) - 1),
        "canonical": canonical,
    }


@bp.route("/blindspot")
def index():
    """The Blindspot page. Anonymous / no-active-algorithm visitors get
    the onboarding empty state; everyone else gets the computed list."""
    weights, active_algo_id = _active_weights_and_algo()

    if not active_algo_id:
        return render_template(
            "blindspot.html",
            blindspots=[], onboarding=True, error=False,
        )

    cfg = current_app.config
    if not cfg.get("BLINDSPOT_ENABLED", True):
        return render_template(
            "blindspot.html",
            blindspots=[], onboarding=False, error=False,
            disabled=True,
        )

    window_hours = int(cfg.get("BLINDSPOT_WINDOW_HOURS", 48) or 48)
    min_outlets = int(cfg.get("BLINDSPOT_MIN_OUTLETS", 5) or 5)
    max_items = int(cfg.get("BLINDSPOT_MAX_ITEMS", 8) or 8)

    try:
        big = _big_stories(window_hours, min_outlets, CANDIDATE_CAP)
        if not big:
            return render_template(
                "blindspot.html",
                blindspots=[], onboarding=False, error=False,
                window_hours=window_hours, min_outlets=min_outlets,
            )

        candidate_ids = [r["story_id"] for r in big]
        meta = _canonical_meta(candidate_ids)
        mute_terms = _mute_terms_for(active_algo_id)

        mute_hits = {}
        for sid in candidate_ids:
            m = meta.get(sid)
            if not m:
                continue
            hit = _mute_hit(m, mute_terms)
            if hit:
                mute_hits[sid] = hit

        survivors = _filter_survivors(weights, candidate_ids)
        # Don't double-count mute hits as filter hits: mute wins anyway
        # in classify_blindspots, but skipping here keeps the helper
        # call's filter_hits set semantically clean (it's the set of
        # things the *hard filters* excluded, not the union).
        filter_hits = {
            sid for sid in candidate_ids
            if sid not in survivors and sid not in mute_hits
        }

        shown = _selected_story_ids(weights, active_algo_id, limit=SELECT_POOL)

        picked = classify_blindspots(
            big, shown_story_ids=shown,
            mute_hits=mute_hits, filter_hits=filter_hits,
            max_items=max_items,
        )

        items = []
        for p in picked:
            sid = p["story_id"]
            m = meta.get(sid)
            if not m:
                # The canonical disappeared between queries (retention
                # prune raced us). Skip rather than render a headline-less
                # card.
                continue
            sp = _spectrum_for(sid)
            items.append({
                "story_id": sid,
                "title": m["title"],
                "summary": m["summary"],
                "outlet_count": p["outlet_count"],
                "hidden_reason": p["hidden_reason"],
                "mute_term": p.get("mute_term"),
                "reason_label": reason_label(
                    p["hidden_reason"], term=p.get("mute_term")
                ),
                "spectrum": sp,
            })

        return render_template(
            "blindspot.html",
            blindspots=items, onboarding=False, error=False,
            window_hours=window_hours, min_outlets=min_outlets,
        )
    except Exception:
        current_app.logger.exception("blindspot index failed")
        return render_template(
            "blindspot.html",
            blindspots=[], onboarding=False, error=True,
        )
