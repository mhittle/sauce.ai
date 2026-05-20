"""Anthropic LLM classifier with prompt caching.

The classifier is optional: if no API key is configured, the caller should fall
back to source-level defaults. The pipeline must never crash because the LLM is
unavailable.
"""
import json
import os
from typing import List, Tuple

from .schema import SYSTEM_PROMPT, USER_TEMPLATE, render_articles_block


class LLMUnavailable(Exception):
    pass


# Rough $/Mtok prices for cost estimation (Haiku 4.5 ballpark).
PRICES = {
    "input": 1.00,        # $ per 1M input tokens
    "output": 5.00,       # $ per 1M output tokens
    "cache_read": 0.10,   # $ per 1M cached input tokens
}


def _estimate_cost(usage) -> float:
    if not usage:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    cost = (inp / 1_000_000) * PRICES["input"]
    cost += (out / 1_000_000) * PRICES["output"]
    cost += (cached / 1_000_000) * PRICES["cache_read"]
    return cost


def classify_batch_llm(api_key: str, model: str, articles: List[Tuple]) -> dict:
    """articles: list of (id, source_name, source_lean, title, summary).

    Returns: {"by_id": {id: {political_lean, objectivity}}, "usage": {...}}
    Raises LLMUnavailable on any failure; caller should fall back.
    """
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
    if not articles:
        return {"by_id": {}, "usage": {}}

    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")

    client = anthropic.Anthropic(api_key=api_key)
    user_block = USER_TEMPLATE.format(n=len(articles), articles=render_articles_block(articles))

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
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
        raise LLMUnavailable(f"Could not parse LLM JSON: {e}; got: {text[:200]}")

    results = parsed.get("results", [])
    by_id = {}
    for r in results:
        try:
            aid = int(r["id"])
            lean = max(-1.0, min(1.0, float(r.get("political_lean", 0.0))))
            obj = max(0.0, min(1.0, float(r.get("objectivity", 0.5))))
            loc = r.get("primary_location") or ""
            if not isinstance(loc, str):
                loc = ""
            loc = loc.strip()[:120]
            by_id[aid] = {
                "political_lean": lean,
                "objectivity": obj,
                "primary_location": loc,
            }
        except (KeyError, TypeError, ValueError):
            continue

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "model": model,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    return {"by_id": by_id, "usage": usage}
