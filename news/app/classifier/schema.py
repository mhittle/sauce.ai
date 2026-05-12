"""Shared types / prompt schema for the LLM classifier."""

SYSTEM_PROMPT = """You are a news article classifier. For each article, return:
- political_lean: number in [-1, 1]. -1 strongly left, 0 centrist, +1 strongly right. Score the ARTICLE itself (framing, word choice, who is centered) — not the outlet.
- objectivity: number in [0, 1]. 1 = strictly factual reporting. 0 = pure opinion/advocacy.

Be calibrated. A neutral wire-service piece is ~0 lean and ~0.9 objectivity. An op-ed is non-zero lean and <0.4 objectivity. If the text is too short to judge, use 0 and 0.5.

Output STRICT JSON only, matching this exact schema:
{"results": [{"id": <int>, "political_lean": <float>, "objectivity": <float>}, ...]}
No prose, no markdown, no code fences. The number of results MUST equal the number of articles in the input."""

USER_TEMPLATE = """Classify these {n} articles. Respond with JSON only.

{articles}"""


def render_articles_block(items):
    """items: list of (id, source_name, source_lean, title, summary)."""
    lines = []
    for i, src, lean, title, summary in items:
        summary = (summary or "").replace("\n", " ")[:600]
        lines.append(
            f"---\nid: {i}\nsource: {src} (lean={lean:+.2f})\ntitle: {title}\nsummary: {summary}"
        )
    return "\n".join(lines)
