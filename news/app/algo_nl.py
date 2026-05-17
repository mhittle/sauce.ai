"""Natural-language -> ranking-algorithm interpreter.

The user describes the feed they want in plain English; a single Claude
Haiku call maps that description onto the existing 3-axis `FEATURES`
catalog (direction / weight / threshold per feature, plus recency and a
category filter). The result is a normal `weights` dict in exactly the
same on-disk shape `app.ranking` already uses, so the caller can hand it
straight to `resolved_weights_for_view` / `weights_to_expression` /
`build_score_sql` and pre-fill the `/algo` editor for review. Nothing is
ever applied silently — the route renders the editor, the user Saves.

Same conventions as `app.classifier.framing`: Flask-free, lazy
`anthropic` import so tests don't need the SDK, raises `LLMUnavailable`
on any failure so the route can fall back to "editor unchanged".
"""
import json

from .classifier.llm import LLMUnavailable, _estimate_cost
from .ranking import (
    FEATURES,
    FEATURE_KEYS,
    FEATURES_BY_KEY,
    CATEGORIES,
    _scale_width,
)

MAX_DESCRIPTION_CHARS = 1000


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _feature_catalog_block():
    """Build the feature reference the model gets, straight from the
    catalog so the prompt can never drift from `ranking.FEATURES`."""
    lines = []
    for f in FEATURES:
        if f["scale"] == "signed":
            drange = "-1.0 (fully %s) .. 0.0 (center) .. 1.0 (fully %s)" % (
                f["low"].lower(), f["high"].lower())
        else:
            drange = "0.0 (%s) .. 1.0 (%s)" % (f["low"].lower(), f["high"].lower())
        lines.append(
            f'- "{f["key"]}" ({f["label"]}): direction is {drange}. '
            f'default_direction={f["default_direction"]}.'
        )
    return "\n".join(lines)


def _system_prompt():
    return (
        "You translate a reader's plain-English description of the news "
        "feed they want into a ranking-algorithm weight vector.\n\n"
        "Each feature has three knobs:\n"
        "- weight: how much the reader cares (0.0 = ignore, up to 2.0 = "
        "very strong). Leave a feature at 0 unless the description implies "
        "it matters.\n"
        "- direction: where on the feature's scale the reader wants "
        "articles to sit (see ranges below).\n"
        "- threshold: OPTIONAL hard filter. null = off (default). A number "
        "means 'reject articles whose value is further than this distance "
        "from direction'. Only set it when the reader asks to exclude/"
        "hide/only-show something strongly; keep it null otherwise.\n\n"
        "Features:\n"
        f"{_feature_catalog_block()}\n\n"
        "Also:\n"
        "- recency: 0.0 (timeless ok) .. 2.0 (strongly prefer fresh). "
        "Default around 0.7 unless the reader signals otherwise.\n"
        f"- category_filter: optional subset of {CATEGORIES}. Empty = all "
        "categories. Only restrict if the reader clearly wants just "
        "certain topics.\n\n"
        "Guidance: 'less outrage / less opinion / just the facts' -> high "
        "objectivity weight + objectivity direction 1.0. 'hide paywalls' "
        "-> paywall direction 0.0 with a small threshold. 'long / deep / "
        "in-depth reads' -> reading_level + info_density weight up, "
        "direction high. 'from small/independent outlets' -> "
        "source_obscurity. 'balanced / centrist / both sides' -> "
        "political_lean & source_lean direction 0.0 with non-trivial "
        "weight. Map ideological lean requests to political_lean/"
        "source_lean direction, never refuse.\n\n"
        "Output STRICT JSON ONLY, no markdown, no code fences, exactly "
        'this schema: {"weights": {"<feature_key>": {"weight": <num>, '
        '"direction": <num>, "threshold": <num|null>}, ...}, "recency": '
        '<num>, "category_filter": [<str>...], "notes": "<one or two '
        'plain sentences telling the reader what you set and why>"}. '
        "Only use feature keys from the list above. Omit features you are "
        "leaving at zero."
    )


def _normalize(parsed):
    """Coerce the model's JSON into the canonical on-disk weights shape,
    clamping every value into its valid range and dropping anything
    unknown. Returns (weights_dict, notes_str)."""
    weights = {}
    raw_w = parsed.get("weights")
    if not isinstance(raw_w, dict):
        raw_w = {}

    any_active = False
    for fk in FEATURE_KEYS:
        spec = raw_w.get(fk)
        if not isinstance(spec, dict):
            continue
        feat = FEATURES_BY_KEY[fk]
        scale = _scale_width(feat)
        d_lo = -1.0 if feat["scale"] == "signed" else 0.0

        try:
            w = _clamp(float(spec.get("weight", 0) or 0), 0.0, 2.0)
        except (TypeError, ValueError):
            w = 0.0
        try:
            d = _clamp(float(spec.get("direction", feat["default_direction"])),
                       d_lo, 1.0)
        except (TypeError, ValueError):
            d = float(feat["default_direction"])

        th_raw = spec.get("threshold", None)
        if th_raw in (None, "", "off"):
            th = None
        else:
            try:
                th = float(th_raw)
                th = None if th < 0 else _clamp(th, 0.0, scale)
            except (TypeError, ValueError):
                th = None

        weights[fk] = w
        weights[f"{fk}_direction"] = d
        weights[f"{fk}_threshold"] = th
        if w > 0:
            any_active = True

    try:
        rec = _clamp(float(parsed.get("recency", 0) or 0), 0.0, 2.0)
    except (TypeError, ValueError):
        rec = 0.0
    weights["recency"] = rec
    if rec > 0:
        any_active = True

    cats = parsed.get("category_filter") or []
    if isinstance(cats, list):
        weights["category_filter"] = [c for c in cats if c in CATEGORIES]
    else:
        weights["category_filter"] = []

    if not any_active:
        raise LLMUnavailable("model produced no usable weights")

    notes = (parsed.get("notes") or "").strip()
    return weights, notes[:500]


def interpret_algorithm(description, *, api_key, model):
    """Return {"weights": dict, "notes": str, "usage": {...}} or raise
    LLMUnavailable. Makes exactly one Anthropic call per invocation; the
    caller decides whether/when to persist the weights."""
    description = (description or "").strip()
    if not description:
        raise LLMUnavailable("empty description")
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")

    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")

    user_block = (
        "Reader's description of the feed they want:\n\n"
        f"{description[:MAX_DESCRIPTION_CHARS]}\n\n"
        "Respond with JSON only."
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": _system_prompt()}],
            messages=[{"role": "user", "content": user_block}],
            timeout=30.0,
        )
    except Exception as e:
        raise LLMUnavailable(f"Anthropic API error: {e}")

    text = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMUnavailable(f"Could not parse algorithm JSON: {e}; got: {text[:200]}")
    if not isinstance(parsed, dict):
        raise LLMUnavailable("model JSON was not an object")

    weights, notes = _normalize(parsed)

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "model": model,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    return {"weights": weights, "notes": notes, "usage": usage}
