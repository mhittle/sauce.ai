"""Shared types / prompt schema for the LLM classifier."""

SYSTEM_PROMPT = """You are a news article classifier. For each article, return the
following judgments. Be calibrated; default to neutral midpoints when the text
is too short to judge.

  political_lean       — [-1, 1]. -1 strongly left, 0 centrist, +1 strongly right.
                          Score the ARTICLE itself (framing, word choice, who is
                          centered) — not the outlet.
  objectivity          — [0, 1]. 1 = strictly factual reporting. 0 = pure
                          opinion/advocacy.
  tone_calmness        — [0, 1]. 1 = calm, measured. 0 = alarmist, urgent.
  sensationalism       — [0, 1]. 1 = sensational/clickbait phrasing. 0 = plain.
  analysis_depth       — [0, 1]. 1 = analytical / explainer / longform synthesis.
                          0 = breaking-news brief or wire snippet.
  emotional_charge     — [0, 1]. 1 = emotionally loaded language. 0 = neutral.
  hedging              — [0, 1]. 1 = heavy hedging ("may", "could", "experts
                          believe"). 0 = confident assertions.
  solution_orientation — [0, 1]. 1 = solution-focused (what's being done). 0 =
                          problem-focused (what's broken).
  primary_location     — Short string identifying the single US city / state the
                          article is primarily about, formatted as "City, ST"
                          (state abbr) or "ST" if no specific city is named. Use
                          "" (empty string) if the article is national,
                          international, or has no clear US locus. Examples:
                          "Seattle, WA", "TX", "Washington, DC", "". Pick the
                          most central location, not every place mentioned.

Calibration: a neutral wire-service piece is ~0 lean, ~0.9 objectivity,
~0.7 tone_calmness, ~0.1 sensationalism, ~0.3 analysis_depth, ~0.2
emotional_charge, ~0.3 hedging, ~0.5 solution_orientation. An op-ed is
non-zero lean, <0.4 objectivity, higher emotional_charge, lower
tone_calmness. If text is too short to judge, use 0 for lean and 0.5 for
the other scalars. If location is ambiguous, prefer "".

Output STRICT JSON only, matching this exact schema:
{"results": [{"id": <int>, "political_lean": <float>, "objectivity": <float>,
  "tone_calmness": <float>, "sensationalism": <float>,
  "analysis_depth": <float>, "emotional_charge": <float>,
  "hedging": <float>, "solution_orientation": <float>,
  "primary_location": <string>}, ...]}
No prose, no markdown, no code fences. The number of results MUST equal the
number of articles in the input."""

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
