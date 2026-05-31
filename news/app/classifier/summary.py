"""Anthropic 3-bullet TL;DR summarizer — a separate, isolated pass.

Runs after body extraction in `jobs/classify_pending.py`, only on gated
articles (source_reputation above a floor, paywall below a ceiling, and a
real extracted body present). Deliberately decoupled from the load-bearing
judgments call (`classify_batch_llm`): a summarization failure must never
degrade ranking or stall classification, so the caller swallows
`LLMUnavailable` and continues. Summaries are generated from the extracted
article body (not the RSS blurb) for fidelity.
"""
import json
from typing import List, Tuple

from .llm import LLMUnavailable, _estimate_cost

MAX_BULLETS = 3
MAX_BULLET_CHARS = 240
# Cap body input per article so a long longform piece can't blow up
# input-token cost. ~6k chars is roughly 1.5k tokens — plenty for a TL;DR.
DEFAULT_MAX_BODY_CHARS = 6000

SUMMARY_SYSTEM_PROMPT = """You write concise 3-bullet TL;DR summaries of news articles.
For each article, return up to 3 short bullets (each a single sentence, under
30 words) capturing the key facts a reader needs to decide whether to read the
full piece. Lead with the most important fact. Be neutral and factual: no
opinion, no editorializing, no clickbait, no second person. Do not begin a
bullet with "The article", "This story", or the outlet name. If the text is
too thin to summarize, return an empty list for that article.

Output STRICT JSON only, matching this exact schema:
{"results": [{"id": <int>, "bullets": ["...", "...", "..."]}, ...]}
No prose, no markdown, no code fences. The number of results MUST equal the
number of articles in the input; use an empty bullets list when unsure."""

SUMMARY_USER_TEMPLATE = """Summarize these {n} articles. Respond with JSON only.

{articles}"""


def sanitize_bullets(raw) -> List[str]:
    """Coerce arbitrary LLM/stored output into a clean list of <=MAX_BULLETS
    non-empty bullet strings, each trimmed to MAX_BULLET_CHARS. Tolerant of
    None, non-lists, and non-string items so neither the writer (untrusted
    model output) nor the reader (stored JSON) can raise on bad data."""
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split()).strip()
        if not text:
            continue
        out.append(text[:MAX_BULLET_CHARS])
        if len(out) >= MAX_BULLETS:
            break
    return out


def render_articles_block(items, max_body_chars=DEFAULT_MAX_BODY_CHARS) -> str:
    """items: list of (id, title, body_text)."""
    lines = []
    for i, title, body in items:
        body = " ".join((body or "").split())[:max_body_chars]
        lines.append(f"---\nid: {i}\ntitle: {title}\nbody: {body}")
    return "\n".join(lines)


def summarize_batch_llm(api_key: str, model: str, items: List[Tuple],
                        max_body_chars: int = DEFAULT_MAX_BODY_CHARS) -> dict:
    """items: list of (id, title, body_text).

    Returns: {"by_id": {id: [bullet, ...]}, "usage": {...}}.
    Raises LLMUnavailable on any failure; caller should swallow it (the TL;DR
    is non-critical enrichment). Articles the model omits or returns empty
    bullets for simply don't appear in by_id.
    """
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
    if not items:
        return {"by_id": {}, "usage": {}}

    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")

    client = anthropic.Anthropic(api_key=api_key)
    user_block = SUMMARY_USER_TEMPLATE.format(
        n=len(items), articles=render_articles_block(items, max_body_chars))

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SUMMARY_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
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
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMUnavailable(f"Could not parse summary JSON: {e}; got: {text[:200]}")

    by_id = {}
    for r in parsed.get("results", []):
        try:
            aid = int(r["id"])
        except (KeyError, TypeError, ValueError):
            continue
        bullets = sanitize_bullets(r.get("bullets"))
        if bullets:
            by_id[aid] = bullets

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "model": model,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    return {"by_id": by_id, "usage": usage}
