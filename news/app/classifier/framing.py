"""LLM-generated framing summary for a story dossier.

Given the set of articles in a deduplicated story cluster (typically 3-12
items spanning multiple political-lean buckets), produces a 2-4 sentence
"how did different sides frame this story" summary. Used by the
`/story/<id>` dossier page and cached per cluster-member signature in the
`story_dossiers` table.

Same shape as `app.classifier.llm.classify_batch_llm`: takes the api key
and model, raises `LLMUnavailable` on any failure, returns a dict with
`summary` and a `usage` block. Anthropic SDK is imported lazily so unit
tests don't need it installed.
"""

from .llm import LLMUnavailable, _estimate_cost


SYSTEM_PROMPT = (
    "You are a news framing analyst. You receive a deduplicated cluster "
    "of news articles all covering the same story from multiple outlets "
    "spanning the political spectrum. Each article carries the outlet's "
    "lean (a number in [-1, 1]) and the article's own lean. Write a "
    "concise framing summary (2-4 sentences, prose, no bullet points) "
    "describing how coverage differs across the spectrum. Lead with what "
    "the outlets agree on, then explicitly contrast left-leaning vs "
    "right-leaning emphasis where it diverges. Use neutral, descriptive "
    "language. Refer to groupings ('left-leaning sources', 'right-leaning "
    "sources', 'wire services') rather than naming individual outlets. "
    "Do not editorialize. Output STRICT JSON only, matching this exact "
    'schema: {"summary": "<text>"}. No prose, no markdown, no code '
    "fences outside the JSON."
)


def _render_members_block(members):
    """members: list of dicts with source_name, source_lean, political_lean,
    title, lead. Produces a compact prompt block."""
    lines = []
    for m in members:
        lead = (m.get("lead") or "").replace("\n", " ").strip()[:400]
        lines.append(
            "---\n"
            f"source: {m['source_name']} (outlet_lean={float(m.get('source_lean', 0.0)):+.2f}, "
            f"article_lean={float(m.get('political_lean', 0.0)):+.2f})\n"
            f"headline: {m['title']}\n"
            f"lead: {lead}"
        )
    return "\n".join(lines)


def generate_framing(members, *, api_key, model, max_members=12):
    """Return {"summary": str, "usage": {...}} or raise LLMUnavailable.

    Caller is responsible for caching the result. This function makes one
    Anthropic API call per invocation.
    """
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
    if not members:
        raise LLMUnavailable("no members supplied")

    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")

    capped = list(members)[:max_members]
    user_block = (
        f"Cluster of {len(capped)} articles covering one story.\n\n"
        f"{_render_members_block(capped)}\n\n"
        "Respond with JSON only."
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
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

    import json
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMUnavailable(f"Could not parse framing JSON: {e}; got: {text[:200]}")

    summary = (parsed.get("summary") or "").strip()
    if not summary:
        raise LLMUnavailable("Framing summary was empty")

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "model": model,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    return {"summary": summary, "usage": usage}
