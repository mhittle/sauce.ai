import json
from flask import (
    Blueprint, render_template, request, redirect, url_for, g, jsonify,
    current_app,
)

from ..auth import login_required
from ..db import query, execute, get_conn
from ..algo_nl import interpret_algorithm
from ..classifier import LLMUnavailable
from ..onboarding import (
    LEAN_CHOICES, DEFAULT_LEAN_KEY, TRUSTED_SOURCE_WEIGHT,
    build_onboarding_weights, top_trusted_sources,
)
from ..ranking import (
    PRESETS, FEATURES, FEATURE_KEYS, SIGNED_FEATURES, CATEGORIES,
    COUNTRIES, GEO_RADIUS_MAX_MI, GEO_RADIUS_DEFAULT_MI,
    default_weights, parse_weights_json, weights_to_expression,
    build_score_sql, build_filters_sql, resolved_weights_for_view,
)
from ..term_prefs import normalize_term, clamp_boost, BOOST_DEFAULT, VALID_MODES
from ..geo import geocode_query

MAX_KEYWORDS_PER_ALGO = 100

bp = Blueprint("algo", __name__)


def _get_active(user_id):
    row = query(
        "SELECT id, weights_json FROM user_algorithms WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
        (user_id,), one=True,
    )
    if not row:
        return None, default_weights()
    return row["id"], parse_weights_json(row["weights_json"])


def _list_profiles(user_id):
    return query(
        "SELECT id, name, is_active FROM user_algorithms WHERE user_id = %s "
        "ORDER BY is_active DESC, updated_at DESC",
        (user_id,),
    ) or []


def _set_active(user_id, algo_id):
    """Promote one profile to active and demote the rest. The feed / firehose /
    digest resolvers all read `is_active = 1 ... LIMIT 1`, so exactly one row
    per user must carry the flag — enforce that here atomically."""
    execute("UPDATE user_algorithms SET is_active = 0 WHERE user_id = %s", (user_id,))
    execute(
        "UPDATE user_algorithms SET is_active = 1 WHERE id = %s AND user_id = %s",
        (algo_id, user_id),
    )
    get_conn().commit()


def _clean_name(raw, fallback="Custom"):
    return ((raw or "").strip()[:120]) or fallback


def _return_redirect():
    """The feed switcher posts here too; send it back where it came from.
    Whitelisted targets only — never reflect a caller-supplied URL."""
    if request.form.get("return_to") == "feed":
        return redirect(url_for("feed.index"))
    return redirect(url_for("algo.index"))


def _parse_form_weights(form):
    """Pull direction + weight + threshold per feature from the algo form."""
    weights = {}
    for fk in FEATURE_KEYS:
        try:
            weights[fk] = float(form.get(f"w_{fk}", 0) or 0)
        except ValueError:
            weights[fk] = 0.0
        try:
            weights[f"{fk}_direction"] = float(form.get(f"d_{fk}", 0) or 0)
        except ValueError:
            weights[f"{fk}_direction"] = 0.0
        raw_th = form.get(f"th_{fk}")
        if raw_th in (None, "", "off"):
            weights[f"{fk}_threshold"] = None
        else:
            try:
                weights[f"{fk}_threshold"] = float(raw_th)
            except ValueError:
                weights[f"{fk}_threshold"] = None
    try:
        weights["recency"] = float(form.get("w_recency", 0) or 0)
    except ValueError:
        weights["recency"] = 0.0
    weights["category_filter"] = [c for c in form.getlist("category_filter") if c in CATEGORIES]
    weights["country_filter"] = [c for c in form.getlist("country_filter") if c in COUNTRIES]
    # Unchecked HTML checkboxes don't submit, so set this every save rather
    # than relying on key presence — otherwise toggling off would never
    # clear the previously-saved truthy value.
    weights["unique_sources"] = bool(form.get("unique_sources"))

    # Geo radius filter: free-text place + radius. Resolve the place once at
    # save time so the SQL layer can stay dumb. An unparseable place silently
    # clears the filter rather than 400ing — same forgiving feel as the
    # natural-language slider builder.
    geo_query = (form.get("geo_query") or "").strip()
    try:
        geo_radius = float(form.get("geo_radius_mi") or 0)
    except ValueError:
        geo_radius = 0.0
    if geo_query and geo_radius > 0:
        resolved = geocode_query(geo_query)
        if resolved:
            lat, lng, label = resolved
            weights["geo_lat"] = lat
            weights["geo_lng"] = lng
            weights["geo_radius_mi"] = min(geo_radius, float(GEO_RADIUS_MAX_MI))
            weights["geo_query"] = geo_query
            weights["geo_label"] = label
        else:
            # Keep the query string so the editor can show "couldn't resolve",
            # but null the active filter so SQL ignores it.
            weights["geo_query"] = geo_query
            weights["geo_label"] = ""
            weights["geo_lat"] = None
            weights["geo_lng"] = None
            weights["geo_radius_mi"] = None
    else:
        weights["geo_query"] = geo_query
        weights["geo_label"] = ""
        weights["geo_lat"] = None
        weights["geo_lng"] = None
        weights["geo_radius_mi"] = None
    return weights


def _load_algo_terms(algo_id):
    """Return (muted, boosted) rows for an algorithm, or two empty lists if
    the user has no active algorithm yet (pre-onboarding)."""
    if not algo_id:
        return [], []
    rows = query(
        "SELECT id, term, mode, weight, created_at "
        "FROM algorithm_term_prefs WHERE algorithm_id = %s ORDER BY mode, term",
        (algo_id,),
    ) or []
    return (
        [r for r in rows if r["mode"] == "mute"],
        [r for r in rows if r["mode"] == "boost"],
    )


def _parse_nl_keywords(form):
    """Re-sanitize the NL-proposed keyword chips that ride through the algo
    form as parallel hidden inputs. The client (Alpine) can drop chips before
    saving, but everything submitted is re-validated here — the form is
    untrusted. Returns an insertion-ordered list of {term, mode, weight},
    deduped with mute winning over boost (same rule as build_term_clauses)."""
    terms = form.getlist("nl_kw_term")
    modes = form.getlist("nl_kw_mode")
    weights = form.getlist("nl_kw_weight")
    out = {}
    for i, raw_term in enumerate(terms):
        term = normalize_term(raw_term)
        if term is None:
            continue
        mode = (modes[i] if i < len(modes) else "").strip().lower()
        if mode not in VALID_MODES:
            continue
        if mode == "boost":
            weight = clamp_boost(weights[i] if i < len(weights) else None)
        else:
            weight = BOOST_DEFAULT
        if term in out:
            if mode == "mute" and out[term]["mode"] != "mute":
                out[term] = {"term": term, "mode": "mute", "weight": BOOST_DEFAULT}
            continue
        out[term] = {"term": term, "mode": mode, "weight": weight}
    return list(out.values())


def _apply_nl_keywords(algo_id, form):
    """Persist the NL-proposed keywords into one profile's
    `algorithm_term_prefs`, respecting the per-profile cap. Caller commits.
    Idempotent: re-adding a term updates its mode/weight (same upsert as the
    manual add path)."""
    proposed = _parse_nl_keywords(form)
    if not proposed:
        return
    count_row = query(
        "SELECT COUNT(*) AS n FROM algorithm_term_prefs WHERE algorithm_id = %s",
        (algo_id,), one=True,
    )
    existing = {
        r["term"] for r in (query(
            "SELECT term FROM algorithm_term_prefs WHERE algorithm_id = %s",
            (algo_id,),
        ) or [])
    }
    room = MAX_KEYWORDS_PER_ALGO - (count_row["n"] if count_row else 0)
    for kw in proposed:
        if kw["term"] not in existing:
            if room <= 0:
                break
            room -= 1
        execute(
            "INSERT INTO algorithm_term_prefs (algorithm_id, term, mode, weight) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE mode = VALUES(mode), weight = VALUES(weight)",
            (algo_id, kw["term"], kw["mode"], kw["weight"]),
        )


def _render_editor(weights, *, nl_description="", nl_notes=None, nl_error=None,
                   kw_error=None, nl_keywords=None):
    profiles = _list_profiles(g.user["id"])
    active_id = next((p["id"] for p in profiles if p["is_active"]), None)
    algo_muted, algo_boosted = _load_algo_terms(active_id)
    return render_template(
        "algo.html",
        weights=resolved_weights_for_view(weights),
        features=FEATURES,
        feature_keys=FEATURE_KEYS,
        signed_features=SIGNED_FEATURES,
        categories=CATEGORIES,
        countries=COUNTRIES,
        geo_radius_max=GEO_RADIUS_MAX_MI,
        geo_radius_default=GEO_RADIUS_DEFAULT_MI,
        expression=weights_to_expression(weights),
        presets=PRESETS,
        profiles=profiles,
        active_algo_id=active_id,
        nl_description=nl_description,
        nl_notes=nl_notes,
        nl_error=nl_error,
        algo_muted=algo_muted,
        algo_boosted=algo_boosted,
        max_keywords=MAX_KEYWORDS_PER_ALGO,
        boost_default=BOOST_DEFAULT,
        kw_error=kw_error,
        nl_keywords=nl_keywords or [],
    )


@bp.route("/")
@login_required
def index():
    aid, weights = _get_active(g.user["id"])
    return _render_editor(weights)


@bp.route("/describe", methods=["POST"])
@login_required
def describe():
    """Map a plain-English description onto the weight vector and re-render
    the editor pre-filled for review. Never saves; never 500s — on any LLM
    failure the editor comes back with the user's current weights and an
    inline note to adjust the sliders directly."""
    description = (request.form.get("description") or "").strip()
    aid, current = _get_active(g.user["id"])
    if not description:
        return _render_editor(
            current, nl_error="Describe the feed you want in a sentence or two.")
    cfg = current_app.config
    try:
        result = interpret_algorithm(
            description,
            api_key=cfg.get("ANTHROPIC_API_KEY", ""),
            model=cfg.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        )
    except LLMUnavailable:
        return _render_editor(
            current,
            nl_description=description,
            nl_error="Couldn't turn that into an algorithm right now. "
                     "Adjust the sliders directly, or try rephrasing.",
        )
    notes = result["notes"] or (
        "Here's a starting point based on your description.")
    return _render_editor(
        result["weights"], nl_description=description, nl_notes=notes,
        nl_keywords=result.get("keywords") or [])


def _has_algorithm(user_id):
    row = query(
        "SELECT COUNT(*) AS n FROM user_algorithms WHERE user_id = %s",
        (user_id,), one=True,
    )
    return bool(row and row["n"])


def _trusted_source_pool():
    rows = query(
        "SELECT id, name, source_reputation, source_lean, category "
        "FROM sources WHERE owner_id IS NULL AND is_active = 1 "
        "ORDER BY source_reputation DESC, name ASC LIMIT 60"
    )
    return top_trusted_sources(rows or [], limit=12)


@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    # Idempotent: once the reader has an algorithm, don't re-interview or
    # stack a second active row — send them to the editor.
    if _has_algorithm(g.user["id"]):
        return redirect(url_for("algo.index"))

    if request.method == "POST":
        weights = build_onboarding_weights(
            categories=request.form.getlist("categories"),
            lean_key=request.form.get("lean", DEFAULT_LEAN_KEY),
        )
        execute(
            "INSERT INTO user_algorithms (user_id, name, weights_json, expression_text, is_active) VALUES (%s, %s, %s, %s, 1)",
            (g.user["id"], "My starting feed", json.dumps(weights), weights_to_expression(weights)),
        )

        requested = []
        for v in request.form.getlist("sources"):
            try:
                requested.append(int(v))
            except (TypeError, ValueError):
                pass
        if requested:
            placeholders = ",".join(["%s"] * len(requested))
            valid = query(
                f"SELECT id FROM sources WHERE id IN ({placeholders}) "
                f"AND owner_id IS NULL AND is_active = 1",
                tuple(requested),
            )
            for r in valid or []:
                execute(
                    "INSERT INTO user_source_prefs (user_id, source_id, weight) "
                    "VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE weight = VALUES(weight)",
                    (g.user["id"], r["id"], TRUSTED_SOURCE_WEIGHT),
                )

        get_conn().commit()
        return redirect(url_for("feed.index"))

    return render_template(
        "onboarding.html",
        categories=CATEGORIES,
        lean_choices=LEAN_CHOICES,
        default_lean=DEFAULT_LEAN_KEY,
        sources=_trusted_source_pool(),
    )


@bp.route("/save", methods=["POST"])
@login_required
def save():
    weights = _parse_form_weights(request.form)
    aid, _ = _get_active(g.user["id"])
    if aid:
        execute(
            "UPDATE user_algorithms SET weights_json=%s, expression_text=%s WHERE id=%s AND user_id=%s",
            (json.dumps(weights), weights_to_expression(weights), aid, g.user["id"]),
        )
    else:
        aid = execute(
            "INSERT INTO user_algorithms (user_id, name, weights_json, expression_text, is_active) VALUES (%s, %s, %s, %s, 1)",
            (g.user["id"], "Custom", json.dumps(weights), weights_to_expression(weights)),
        )
    _apply_nl_keywords(aid, request.form)
    get_conn().commit()

    if request.headers.get("HX-Request"):
        return _preview_partial(weights)
    return redirect(url_for("algo.index"))


@bp.route("/profiles/create", methods=["POST"])
@login_required
def create_profile():
    """Save the current editor sliders as a brand-new named profile and make
    it active. This is the multi-profile entry point and the place the NL
    builder's proposed weights get persisted (the form carries them)."""
    weights = _parse_form_weights(request.form)
    name = _clean_name(request.form.get("profile_name"))
    # Reuse a same-named profile instead of stacking a duplicate (BUG-025):
    # saving "Morning brief" again overwrites the existing one and activates
    # it, so the switcher never accumulates repeated names.
    existing = query(
        "SELECT id FROM user_algorithms WHERE user_id = %s AND name = %s "
        "ORDER BY updated_at DESC LIMIT 1",
        (g.user["id"], name), one=True,
    )
    if existing:
        target_id = existing["id"]
        execute(
            "UPDATE user_algorithms SET weights_json=%s, expression_text=%s WHERE id=%s AND user_id=%s",
            (json.dumps(weights), weights_to_expression(weights), target_id, g.user["id"]),
        )
    else:
        target_id = execute(
            "INSERT INTO user_algorithms (user_id, name, weights_json, expression_text, is_active) "
            "VALUES (%s, %s, %s, %s, 0)",
            (g.user["id"], name, json.dumps(weights), weights_to_expression(weights)),
        )
    _apply_nl_keywords(target_id, request.form)
    _set_active(g.user["id"], target_id)
    return redirect(url_for("algo.index"))


@bp.route("/profiles/activate", methods=["POST"])
@login_required
def activate_profile():
    try:
        algo_id = int(request.form.get("algo_id", 0))
    except (TypeError, ValueError):
        algo_id = 0
    owned = query(
        "SELECT id FROM user_algorithms WHERE id = %s AND user_id = %s",
        (algo_id, g.user["id"]), one=True,
    )
    if owned:
        _set_active(g.user["id"], algo_id)
    return _return_redirect()


@bp.route("/profiles/rename", methods=["POST"])
@login_required
def rename_profile():
    try:
        algo_id = int(request.form.get("algo_id", 0))
    except (TypeError, ValueError):
        algo_id = 0
    name = _clean_name(request.form.get("profile_name"))
    execute(
        "UPDATE user_algorithms SET name = %s WHERE id = %s AND user_id = %s",
        (name, algo_id, g.user["id"]),
    )
    get_conn().commit()
    return redirect(url_for("algo.index"))


@bp.route("/profiles/delete", methods=["POST"])
@login_required
def delete_profile():
    try:
        algo_id = int(request.form.get("algo_id", 0))
    except (TypeError, ValueError):
        algo_id = 0
    profiles = _list_profiles(g.user["id"])
    # Refuse to delete the last profile: a user with zero rows gets bounced
    # back into onboarding by feed._needs_onboarding(), losing their tuning.
    if len(profiles) <= 1 or algo_id not in {p["id"] for p in profiles}:
        return redirect(url_for("algo.index"))
    was_active = any(p["id"] == algo_id and p["is_active"] for p in profiles)
    execute(
        "DELETE FROM user_algorithms WHERE id = %s AND user_id = %s",
        (algo_id, g.user["id"]),
    )
    get_conn().commit()
    if was_active:
        survivor = next(p["id"] for p in profiles if p["id"] != algo_id)
        _set_active(g.user["id"], survivor)
    return redirect(url_for("algo.index"))


@bp.route("/preview", methods=["POST"])
@login_required
def preview():
    weights = _parse_form_weights(request.form)
    return _preview_partial(weights)


def _preview_partial(weights):
    score_expr, score_params = build_score_sql(weights)
    filter_sql, filter_params = build_filters_sql(weights)
    sql = f"""
      SELECT a.id, a.title, s.name AS source_name, f.political_lean, f.objectivity,
             ({score_expr}) AS score
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      WHERE a.status = 'classified'
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        {filter_sql}
      ORDER BY score DESC
      LIMIT 8
    """
    params = {**score_params, **filter_params}
    rows = query(sql, params)
    expression = weights_to_expression(weights)
    return render_template("partials/preview.html", preview=rows, expression=expression)


def _owned_algo_id(user_id, algo_id):
    """Confirm a user owns this algorithm before mutating its keywords —
    a forged `algo_id` from the form must never reach `algorithm_term_prefs`."""
    row = query(
        "SELECT id FROM user_algorithms WHERE id = %s AND user_id = %s",
        (algo_id, user_id), one=True,
    )
    return row["id"] if row else None


@bp.route("/keywords/add", methods=["POST"])
@login_required
def add_keyword():
    """Attach a mute/boost term to one of the user's algorithms. Defaults to
    the active algorithm; the form can pass `algo_id` to target a specific
    profile (validated via ownership)."""
    uid = g.user["id"]
    try:
        algo_id = int(request.form.get("algo_id", 0) or 0)
    except (TypeError, ValueError):
        algo_id = 0
    if not algo_id:
        algo_id, _ = _get_active(uid)
    target = _owned_algo_id(uid, algo_id) if algo_id else None
    if not target:
        weights = _active_weights_for_view(uid)
        return _render_editor(
            weights, kw_error="Save an algorithm first, then add keywords."
        )

    mode = (request.form.get("mode") or "").strip().lower()
    if mode not in VALID_MODES:
        weights = _active_weights_for_view(uid)
        return _render_editor(weights, kw_error="Pick mute or boost.")

    term = normalize_term(request.form.get("term"))
    if term is None:
        weights = _active_weights_for_view(uid)
        return _render_editor(
            weights,
            kw_error="Enter a keyword or phrase (at least 2 characters).",
        )

    weight = clamp_boost(request.form.get("weight")) if mode == "boost" else BOOST_DEFAULT

    count_row = query(
        "SELECT COUNT(*) AS n FROM algorithm_term_prefs WHERE algorithm_id = %s",
        (target,), one=True,
    )
    existing = query(
        "SELECT id FROM algorithm_term_prefs WHERE algorithm_id = %s AND term = %s",
        (target, term), one=True,
    )
    if not existing and count_row and count_row["n"] >= MAX_KEYWORDS_PER_ALGO:
        weights = _active_weights_for_view(uid)
        return _render_editor(
            weights,
            kw_error=f"This profile is at the keyword cap ({MAX_KEYWORDS_PER_ALGO}). "
                     f"Remove one before adding another.",
        )

    # A term has exactly one mode per algorithm; re-adding it in the other
    # mode just moves it (mirrors user_term_prefs semantics).
    execute(
        "INSERT INTO algorithm_term_prefs (algorithm_id, term, mode, weight) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE mode = VALUES(mode), weight = VALUES(weight)",
        (target, term, mode, weight),
    )
    get_conn().commit()
    return redirect(url_for("algo.index"))


@bp.route("/keywords/<int:tid>/delete", methods=["POST"])
@login_required
def delete_keyword(tid):
    """Delete via a JOIN against `user_algorithms` so an attacker can't
    remove someone else's keyword by guessing an id."""
    uid = g.user["id"]
    execute(
        "DELETE atp FROM algorithm_term_prefs atp "
        "JOIN user_algorithms ua ON ua.id = atp.algorithm_id "
        "WHERE atp.id = %s AND ua.user_id = %s",
        (tid, uid),
    )
    get_conn().commit()
    return redirect(url_for("algo.index"))


def _active_weights_for_view(user_id):
    _, weights = _get_active(user_id)
    return weights


@bp.route("/use_preset/<key>", methods=["POST"])
@login_required
def use_preset(key):
    if key not in PRESETS:
        return redirect(url_for("algo.index"))
    preset = PRESETS[key]
    weights = preset["weights"].copy()
    weights["category_filter"] = preset.get("category_filter", [])
    aid, _ = _get_active(g.user["id"])
    if aid:
        execute(
            "UPDATE user_algorithms SET name=%s, weights_json=%s, expression_text=%s WHERE id=%s AND user_id=%s",
            (preset["label"], json.dumps(weights), weights_to_expression(weights), aid, g.user["id"]),
        )
    else:
        execute(
            "INSERT INTO user_algorithms (user_id, name, weights_json, expression_text, is_active) VALUES (%s, %s, %s, %s, 1)",
            (g.user["id"], preset["label"], json.dumps(weights), weights_to_expression(weights)),
        )
    get_conn().commit()
    return redirect(url_for("algo.index"))
