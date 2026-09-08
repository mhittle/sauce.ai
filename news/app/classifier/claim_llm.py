"""The three /claim model calls: locate, extract, grade.

Same shape as `classifier/summary.py` / `app/ask.py`: lazy `anthropic`
import, 30 s timeout, any failure -> `LLMUnavailable` (the route renders
an inline "couldn't check this one", never a 500), and a `usage` block the
`llm_usage` writer understands. Structured output is requested through
`output_config.format` (strict JSON schema); if the API rejects it for a
model, the call is retried once without and the text is parsed as JSON.
"""
import json

from .claim_prompts import (
    EXTRACT_SCHEMA, EXTRACT_SYSTEM, EXTRACT_USER_TEMPLATE,
    GRADE_SCHEMA, GRADE_SYSTEM, GRADE_USER_TEMPLATE,
    LOCATE_SCHEMA, LOCATE_SYSTEM, LOCATE_USER_TEMPLATE,
    MAX_ABSTRACT_CHARS, MAX_BODY_CHARS,
)
from .llm import LLMUnavailable, _estimate_cost

MAX_EXCERPT_CHARS = 2500

# $/Mtok (input, output, cache read) by model-id substring; Haiku pricing
# otherwise via `_estimate_cost`.
_PRICES = (
    ("sonnet-5", (2.00, 10.00, 0.20)),
    ("sonnet", (3.00, 15.00, 0.30)),
    ("opus", (5.00, 25.00, 0.50)),
)


def estimate_cost(model, usage):
    for key, (inp, out, cached) in _PRICES:
        if key in (model or ""):
            i = getattr(usage, "input_tokens", 0) or 0
            o = getattr(usage, "output_tokens", 0) or 0
            c = getattr(usage, "cache_read_input_tokens", 0) or 0
            return (i * inp + o * out + c * cached) / 1_000_000
    return _estimate_cost(usage)


def _usage(model, resp):
    u = getattr(resp, "usage", None)
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "model": model,
        "est_cost_usd": estimate_cost(model, u),
    }


def parse_json_text(text):
    """Tolerant JSON parse of a model reply: strips code fences and any
    prose before the first `{` / after the last `}`."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMUnavailable(f"No JSON object in model reply: {t[:120]}")
    try:
        data = json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMUnavailable(f"Could not parse model JSON: {e}; got: {t[:120]}")
    if not isinstance(data, dict):
        raise LLMUnavailable("Model JSON was not an object")
    return data


def _client(api_key):
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")
    return anthropic.Anthropic(api_key=api_key), anthropic


def _call_json(api_key, model, system, user, schema, *, max_tokens):
    client, anthropic = _client(api_key)
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "timeout": 30.0,
    }
    try:
        try:
            resp = client.messages.create(
                output_config={"format": {"type": "json_schema", "schema": schema}}, **kwargs)
        except anthropic.BadRequestError:
            resp = client.messages.create(**kwargs)
    except Exception as e:
        raise LLMUnavailable(f"Anthropic API error: {e}")
    if getattr(resp, "stop_reason", None) == "refusal":
        raise LLMUnavailable("model declined the request")
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", None) == "text")
    return parse_json_text(text), _usage(model, resp)


def _str_or_none(v, limit=300):
    if not isinstance(v, str):
        return None
    v = " ".join(v.split()).strip()
    return v[:limit] or None


def locate_claim(api_key, model, headline, body):
    """-> {"claim", "claim_sentences", "mentions_study", "identifiers",
    "source_kind", "usage"}. Identifier values are trimmed strings or None."""
    body = " ".join((body or "").split())[:MAX_BODY_CHARS]
    user = LOCATE_USER_TEMPLATE.format(headline=(headline or "").strip()[:300], body=body)
    data, usage = _call_json(api_key, model, LOCATE_SYSTEM, user, LOCATE_SCHEMA, max_tokens=1024)
    ids = data.get("identifiers") if isinstance(data.get("identifiers"), dict) else {}
    year = ids.get("year")
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None
    sentences = data.get("claim_sentences")
    sentences = [_str_or_none(s, 600) for s in sentences] if isinstance(sentences, list) else []
    kind = data.get("source_kind")
    return {
        "claim": _str_or_none(data.get("claim"), 400) or (headline or "").strip()[:300],
        "claim_sentences": [s for s in sentences if s][:3],
        "mentions_study": bool(data.get("mentions_study")),
        "identifiers": {
            "doi": _str_or_none(ids.get("doi")),
            "pmid": _str_or_none(ids.get("pmid")),
            "title": _str_or_none(ids.get("title")),
            "first_author": _str_or_none(ids.get("first_author"), 80),
            "journal": _str_or_none(ids.get("journal"), 120),
            "institution": _str_or_none(ids.get("institution"), 120),
            "year": year,
        },
        "source_kind": kind if kind in ("news", "press-release", "blog", "unknown") else "unknown",
        "usage": usage,
    }


def extract_evidence(api_key, model, abstract, *, title="", journal=""):
    """-> {"fields": <raw model fields, unvalidated>, "usage"}. The caller
    MUST run `claim.validate_spans` on `fields` before rendering anything."""
    abstract = " ".join((abstract or "").split())[:MAX_ABSTRACT_CHARS]
    if not abstract:
        raise LLMUnavailable("empty abstract")
    user = EXTRACT_USER_TEMPLATE.format(
        title=(title or "unknown")[:300], journal=(journal or "unknown")[:120], abstract=abstract)
    data, usage = _call_json(api_key, model, EXTRACT_SYSTEM, user, EXTRACT_SCHEMA, max_tokens=2048)
    return {"fields": data, "usage": usage}


def grade_concordance(api_key, model, *, headline, claim, abstract, fields,
                      source_kind="unknown", excerpt=""):
    """-> {"concordance": 0|1|2|None, "concordance_why", "flags": [{flag, why}],
    "usage"}. Flags are filtered to the closed list by `claim.merge_flags`."""
    abstract = " ".join((abstract or "").split())[:MAX_ABSTRACT_CHARS]
    fields = fields or {}

    def val(key):
        item = fields.get(key)
        return item.get("value") if isinstance(item, dict) and item.get("value") else "not stated"

    user = GRADE_USER_TEMPLATE.format(
        headline=(headline or "").strip()[:300],
        claim=(claim or "").strip()[:400],
        source_kind=source_kind or "unknown",
        design=val("design"), species=val("species"), peer_review=val("peer_review"),
        abstract=abstract or "(abstract not available)",
        excerpt=" ".join((excerpt or "").split())[:MAX_EXCERPT_CHARS] or "(none)",
    )
    data, usage = _call_json(api_key, model, GRADE_SYSTEM, user, GRADE_SCHEMA, max_tokens=1024)
    conc = data.get("concordance")
    conc = conc if conc in (0, 1, 2) else None
    flags = data.get("flags") if isinstance(data.get("flags"), list) else []
    return {
        "concordance": conc,
        "concordance_why": _str_or_none(data.get("concordance_why"), 300) or "",
        "flags": flags,
        "usage": usage,
    }
