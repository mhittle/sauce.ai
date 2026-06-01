"""Grounded conversational news over the reader's personalized corpus.

Pure / Flask-free helpers for the "Ask your feed" feature: build the
context block from retrieved articles, assemble multi-turn messages,
reduce a question to FULLTEXT content terms, validate citations, and
gate the daily cap. The Flask route in `app.routes.ask` wires these to
the DB and the Anthropic SDK.

Mirrors the `algo_nl` / `breaking` / `feed_diversify` shape: no Flask,
no DB, no live LLM at import time — easy to unit-test, no fixtures.
"""
import json
import re

from .classifier.llm import LLMUnavailable, _estimate_cost

MAX_QUESTION_CHARS = 2000

# Stopwords + interrogatives that dominate a question but carry no
# retrieval signal. MySQL NATURAL LANGUAGE MODE already drops a built-in
# stopword list, but it doesn't strip interrogatives ("what", "why",
# "how") that pull back off-topic context for question-shaped queries.
# Reducing the question to its salient content terms before MATCH AGAINST
# is the difference between the headline demo working and not.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "of", "in", "on", "at",
    "to", "for", "from", "by", "with", "about", "into", "through", "as",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "doing", "done",
    "have", "has", "had", "having",
    "will", "would", "should", "could", "can", "may", "might", "must",
    "shall", "ought",
    "i", "me", "my", "mine", "you", "your", "yours", "we", "us", "our",
    "ours", "they", "them", "their", "theirs", "he", "she", "it", "its",
    "this", "that", "these", "those",
    "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
    "any", "some", "no", "not", "all", "each", "every", "most", "more",
    "than", "so", "such", "just", "only", "very", "much", "lot", "lots",
    "really", "tell", "show", "give", "say", "said", "says",
    "happened", "happen", "happens", "happening",
    "going", "got", "get", "gets", "getting",
    "yes", "ok", "okay", "please", "thanks", "thank",
    "today", "yesterday", "tomorrow", "week", "month", "year", "day", "now",
    "recent", "recently", "latest", "current", "currently",
    "summarize", "summary", "summarise", "summarised", "summarized",
    "explain", "explained", "explains", "discuss", "discussed", "discusses",
})

# Token shape: keep alphanumeric runs (apostrophes allowed inside a word so
# "covid-19" / "u.s." reduce to "covid" / "u" but "trump's" keeps "trump").
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9']*")
_MAX_TERMS = 12

# Per-turn context + history bounds. Conservative defaults that stay well
# under Haiku's input ceiling and keep cost in low cents per call.
DEFAULT_WINDOW_DAYS = 21
DEFAULT_MAX_CONTEXT_ARTICLES = 18
DEFAULT_MAX_PER_DAY = 25
DEFAULT_MAX_TURNS = 6


def query_terms(question):
    """Reduce a reader question to a space-joined string of content terms
    suitable for FULLTEXT MATCH AGAINST. Drops interrogatives + stopwords
    so a "what happened with the budget bill this week?" query feeds
    `budget bill` to the index instead of a question-shape soup. Returns
    "" when the question is all-stopwords (caller short-circuits with the
    no-coverage path)."""
    if not question:
        return ""
    out = []
    seen = set()
    for tok in _TOKEN_RE.findall(question.lower()):
        if tok in _STOPWORDS or len(tok) < 2:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= _MAX_TERMS:
            break
    return " ".join(out)


def daily_cap_ok(count, max_per_day):
    """True when the user is still under their daily Ask cap. `count` is the
    number of `ask_queries` rows already logged today (UTC); `max_per_day`
    is the cap (0 disables Ask entirely, returning False)."""
    if max_per_day <= 0:
        return False
    return count < max_per_day


def truncate_summary(text, limit=320):
    if not text:
        return ""
    t = " ".join(str(text).split())
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def build_context_block(articles):
    """Format the retrieved rows into the numbered block the model
    grounds on. Each row arrives as a mapping with at minimum `id`,
    `title`, and `source_name`; `summary` and `published_at` are
    optional. The returned text is what the model sees as "the articles
    your feed surfaced" — and the per-article numbering ([1], [2], ...)
    is the citation handle `parse_answer` validates against."""
    lines = []
    for i, a in enumerate(articles, start=1):
        title = (a.get("title") or "").strip()
        source = (a.get("source_name") or a.get("source") or "").strip()
        summary = truncate_summary(a.get("summary"))
        published = a.get("published_at") or ""
        if hasattr(published, "isoformat"):
            published = published.isoformat(sep=" ", timespec="minutes")
        head = f"[{i}] {title}".strip()
        meta_bits = [b for b in (source, str(published)) if b]
        meta = " - ".join(meta_bits)
        line = head
        if meta:
            line += f" ({meta})"
        if summary:
            line += f"\n    {summary}"
        lines.append(line)
    return "\n".join(lines)


def system_prompt():
    return (
        "You answer the reader's question about the news using ONLY the "
        "numbered articles below — articles their own personalized feed "
        "surfaced. These are the reader's sources; do not bring in outside "
        "knowledge, do not speculate, do not invent details.\n\n"
        "Rules:\n"
        "- Cite every concrete claim with a bracketed footnote whose number "
        "matches the article in the list, like [1] or [2][5]. Cite at the end "
        "of the sentence the claim is in, before the period.\n"
        "- If the articles do not actually answer the reader's question, say "
        "\"I don't have coverage of that in your feed\" and stop. Do NOT "
        "answer from training data. Do NOT guess.\n"
        "- Keep the answer tight: 2-5 short paragraphs at most, plain prose. "
        "No headings, no markdown lists, no preamble like \"Based on the "
        "articles...\"\n"
        "- Quote sparingly and only when the exact wording matters; "
        "paraphrase otherwise.\n"
        "- If the reader's question is a follow-up to an earlier turn, treat "
        "the prior conversation as context but still only cite from the "
        "numbered articles below.\n"
        "- Numbers in [brackets] must be ones you actually see in the list; "
        "never cite an article number that isn't there."
    )


def build_messages(history, question, context_block):
    """Assemble the message list the model sees for one turn.

    `history` is an iterable of `(role, text)` from prior turns of the
    same conversation; oldest first. The most recent `DEFAULT_MAX_TURNS`
    pairs are kept (older context loses cheaply — newer questions are
    almost always tighter on relevance). The trailing user message
    bundles the retrieved context with the fresh question."""
    msgs = []
    truncated = list(history or ())[-(DEFAULT_MAX_TURNS * 2):]
    for role, text in truncated:
        if role not in ("user", "assistant"):
            continue
        text = (text or "").strip()
        if not text:
            continue
        msgs.append({"role": role, "content": text})

    user_block = (
        "Articles your feed surfaced (numbered):\n\n"
        f"{context_block}\n\n"
        f"Reader's question: {question.strip()[:MAX_QUESTION_CHARS]}\n\n"
        "Answer using only those articles. Cite with [N]. If they don't "
        "answer the question, say you don't have coverage of that in the "
        "reader's feed."
    )
    msgs.append({"role": "user", "content": user_block})
    return msgs


_CITE_RE = re.compile(r"\[(\d+)\]")


def parse_answer(text, allowed_ids):
    """Extract citation footnotes from the model's reply and drop any that
    don't point at a retrieved article. Returns `(cleaned_text, [int])`
    in the order they appear (deduped). The model can't cite a story it
    wasn't given — a citation outside `allowed_ids` is stripped from the
    rendered text so the reader never sees a broken footnote."""
    allowed = set(int(a) for a in (allowed_ids or ()))
    seen = []
    seen_set = set()

    def _sub(match):
        try:
            n = int(match.group(1))
        except (TypeError, ValueError):
            return ""
        if n not in allowed:
            return ""
        if n not in seen_set:
            seen.append(n)
            seen_set.add(n)
        return f"[{n}]"

    cleaned = _CITE_RE.sub(_sub, text or "")
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    return cleaned.strip(), seen


_NO_COVERAGE_HINT = "don't have coverage"


def is_no_coverage(text):
    """The prompt instructs the model to say "I don't have coverage of that
    in your feed" when the retrieved articles don't answer. The route uses
    this to tag the row `answered=0` so query history reflects which asks
    actually got a grounded answer."""
    return _NO_COVERAGE_HINT in (text or "").lower()


def ask_feed(question, history, articles, *, api_key, model):
    """Issue exactly one Anthropic call grounding `question` on `articles`.

    Returns `{"answer": str, "citations": [int], "answered": bool,
    "usage": {...}}`, or raises `LLMUnavailable` on any failure (the
    route renders an inline error — never a 500). Mirrors the
    `algo_nl.interpret_algorithm` invocation pattern: lazy `anthropic`
    import, 30s timeout, JSON-free plain-text output (citations are in
    line in the prose, not a side channel), usage block compatible with
    the existing `llm_usage` writer.
    """
    question = (question or "").strip()
    if not question:
        raise LLMUnavailable("empty question")
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
    if not articles:
        raise LLMUnavailable("no retrieved articles to ground on")

    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")

    allowed_ids = []
    for i, _ in enumerate(articles, start=1):
        allowed_ids.append(i)
    context = build_context_block(articles)
    messages = build_messages(history, question, context)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": system_prompt()}],
            messages=messages,
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
        text = text.strip("`").strip()

    answer, citations = parse_answer(text, allowed_ids)
    answered = bool(answer) and not is_no_coverage(answer)

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "model": model,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    return {
        "answer": answer,
        "citations": citations,
        "answered": answered,
        "usage": usage,
    }


def serialize_history(rows):
    """Project a list of `ask_queries` rows for one conversation into the
    `(role, text)` history `build_messages` expects. Each DB row carries a
    `question` and may carry an `answer_text`; the latter is best-effort
    decoded from a JSON-ish blob if present, else dropped (the model still
    has the question history to anchor follow-ups)."""
    history = []
    for r in rows or ():
        q = (r.get("question") or "").strip()
        if q:
            history.append(("user", q))
        raw_answer = r.get("answer_text") or ""
        if raw_answer:
            answer = raw_answer
            if raw_answer.startswith("{"):
                try:
                    payload = json.loads(raw_answer)
                    answer = payload.get("answer", "") or answer
                except (TypeError, ValueError):
                    pass
            if answer:
                history.append(("assistant", answer))
    return history
