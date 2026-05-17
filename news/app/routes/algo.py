import json
from flask import (
    Blueprint, render_template, request, redirect, url_for, g, jsonify,
    current_app,
)

from ..auth import login_required
from ..db import query, execute, get_conn
from ..algo_nl import interpret_algorithm
from ..classifier import LLMUnavailable
from ..ranking import (
    PRESETS, FEATURES, FEATURE_KEYS, SIGNED_FEATURES, CATEGORIES,
    default_weights, parse_weights_json, weights_to_expression,
    build_score_sql, build_filters_sql, resolved_weights_for_view,
)

bp = Blueprint("algo", __name__)


def _get_active(user_id):
    row = query(
        "SELECT id, weights_json FROM user_algorithms WHERE user_id = %s AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
        (user_id,), one=True,
    )
    if not row:
        return None, default_weights()
    return row["id"], parse_weights_json(row["weights_json"])


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
    return weights


def _render_editor(weights, *, nl_description="", nl_notes=None, nl_error=None):
    return render_template(
        "algo.html",
        weights=resolved_weights_for_view(weights),
        features=FEATURES,
        feature_keys=FEATURE_KEYS,
        signed_features=SIGNED_FEATURES,
        categories=CATEGORIES,
        expression=weights_to_expression(weights),
        presets=PRESETS,
        nl_description=nl_description,
        nl_notes=nl_notes,
        nl_error=nl_error,
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
        result["weights"], nl_description=description, nl_notes=notes)


@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        preset_key = request.form.get("preset", "balanced")
        if preset_key not in PRESETS:
            preset_key = "balanced"
        preset = PRESETS[preset_key]
        weights = preset["weights"].copy()
        weights["category_filter"] = preset.get("category_filter", [])
        execute(
            "INSERT INTO user_algorithms (user_id, name, weights_json, expression_text, is_active) VALUES (%s, %s, %s, %s, 1)",
            (g.user["id"], preset["label"], json.dumps(weights), weights_to_expression(weights)),
        )
        get_conn().commit()
        return redirect(url_for("feed.index"))
    return render_template("onboarding.html", presets=PRESETS)


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
        execute(
            "INSERT INTO user_algorithms (user_id, name, weights_json, expression_text, is_active) VALUES (%s, %s, %s, %s, 1)",
            (g.user["id"], "Custom", json.dumps(weights), weights_to_expression(weights)),
        )
    get_conn().commit()

    if request.headers.get("HX-Request"):
        return _preview_partial(weights)
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
