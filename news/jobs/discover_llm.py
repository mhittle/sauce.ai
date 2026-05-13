#!/usr/bin/env python3
"""Weekly LLM-suggested source discovery.

For each category in Config.DISCOVER_LLM_CATEGORIES, asks Claude Haiku
for N high-quality RSS feed URLs we don't already have. Suggestions land
in `candidate_sources` with `first_seen_via='llm_agent'`. The nightly
`discover_promote` job validates them like any other candidate — Claude
hallucinations get rejected with `reject_reason='no feed discovered'`
once promotion tries the URL and fails.

The job is idempotent: re-running on the same day produces no new rows
unless the LLM suggests different domains, in which case score
increments and last_seen_at refreshes.

Wrapped in job_lock; safely no-ops if ANTHROPIC_API_KEY is missing.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.discovery import extract_domain, extract_urls

JOB = "discover_llm"
logger = setup_logging(JOB)

VIA = "llm_agent"

SYSTEM_PROMPT = (
    "You are a news editor curating RSS/Atom feeds for a discerning reader. "
    "Given a category and a list of feeds the reader already has, suggest "
    "high-quality, currently-active feeds in that category that the reader "
    "does NOT already have. Prefer outlets with strong editorial standards "
    "and active publishing cadence (multiple articles per week). Avoid "
    "Substack newsletters, abandoned blogs, and single-author rant feeds. "
    "Respond with strict JSON only — no preamble, no commentary."
)

USER_TEMPLATE = (
    "Category: {category}\n"
    "Number of suggestions: {n}\n"
    "Domains the reader already has (sample, do NOT suggest these or any "
    "subdomain of these):\n{existing}\n\n"
    "Return JSON of the form:\n"
    "{{\"suggestions\": [{{\"name\": \"Outlet name\", \"feed_url\": "
    "\"https://outlet.example/rss\", \"why\": \"one-line note\"}}]}}\n"
    "Only include feeds whose URLs you are reasonably confident actually exist."
)

PRICES = {"input": 1.00, "output": 5.00, "cache_read": 0.10}


def _estimate_cost(usage) -> float:
    if not usage:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        (inp / 1_000_000) * PRICES["input"]
        + (out / 1_000_000) * PRICES["output"]
        + (cached / 1_000_000) * PRICES["cache_read"]
    )


def _load_existing_domains(conn, sample_size=40):
    with conn.cursor() as cur:
        cur.execute("SELECT feed_url, homepage FROM sources")
        rows = cur.fetchall()
    domains = []
    for r in rows:
        for u in (r.get("feed_url"), r.get("homepage")):
            d = extract_domain(u or "")
            if d and d not in domains:
                domains.append(d)
    if len(domains) <= sample_size:
        return domains
    return random.sample(domains, sample_size)


def parse_llm_response(text: str) -> list[dict]:
    """Parse Claude's JSON suggestions block. Tolerant of code fences
    and extra prose around the JSON. Returns [] on any parse failure —
    caller logs and continues."""
    if not text:
        return []
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:]
    body = body.strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        urls = extract_urls(text)
        return [{"feed_url": u, "name": "", "why": ""} for u in urls]
    out = []
    for s in parsed.get("suggestions", []):
        url = (s.get("feed_url") or "").strip()
        if not url:
            continue
        out.append({
            "feed_url": url,
            "name": (s.get("name") or "").strip()[:200],
            "why": (s.get("why") or "").strip()[:400],
        })
    return out


def call_claude(api_key: str, model: str, category: str, n: int, existing: list[str]):
    """Returns (suggestions_list, usage_dict). Raises on API failure —
    caller catches and logs."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_block = USER_TEMPLATE.format(
        category=category, n=n, existing="\n".join(f"- {d}" for d in existing) or "(none)"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_block}],
        timeout=30.0,
    )
    text = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    suggestions = parse_llm_response(text)
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    return suggestions, usage


def _record_usage(conn, model, usage, articles):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO llm_usage (model, input_tokens, output_tokens,
                   cache_read_tokens, articles, est_cost_usd)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                model,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_read_tokens", 0),
                articles,
                round(usage.get("est_cost_usd", 0.0), 5),
            ),
        )
    conn.commit()


def _upsert_suggestion(conn, suggestion: dict, category: str, known_domains: set):
    domain = extract_domain(suggestion["feed_url"])
    if not domain or domain in known_domains:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO candidate_sources
                   (domain, feed_url, name, category, score,
                    first_seen_via, last_seen_via,
                    first_seen_at, last_seen_at, state, notes)
               VALUES (%s, %s, %s, %s, 1, %s, %s,
                       UTC_TIMESTAMP(), UTC_TIMESTAMP(), 'pending', %s)
               ON DUPLICATE KEY UPDATE
                   score = score + 1,
                   last_seen_via = VALUES(last_seen_via),
                   last_seen_at = UTC_TIMESTAMP(),
                   feed_url = COALESCE(candidate_sources.feed_url, VALUES(feed_url)),
                   name = COALESCE(NULLIF(candidate_sources.name, ''), VALUES(name)),
                   category = COALESCE(NULLIF(candidate_sources.category, ''), VALUES(category))""",
            (
                domain,
                suggestion["feed_url"][:1024],
                suggestion["name"],
                category,
                VIA,
                VIA,
                suggestion.get("why", "")[:400],
            ),
        )
    return True


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    if not Config.ANTHROPIC_API_KEY:
        logger.info("ANTHROPIC_API_KEY not set; skipping LLM discovery")
        return
    categories = [c.strip() for c in Config.DISCOVER_LLM_CATEGORIES.split(",") if c.strip()]
    if not categories:
        logger.info("no categories configured; skipping")
        return
    conn = get_conn()
    try:
        existing = _load_existing_domains(conn)
        known_set = set(existing)
        total_suggested = 0
        total_inserted = 0
        for cat in categories:
            try:
                suggestions, usage = call_claude(
                    Config.ANTHROPIC_API_KEY,
                    Config.ANTHROPIC_MODEL,
                    cat,
                    Config.DISCOVER_LLM_PER_CATEGORY,
                    existing,
                )
            except Exception as e:
                logger.warning("LLM call failed for %s: %s", cat, e)
                continue
            conn.ping(reconnect=True)
            inserted = 0
            for s in suggestions:
                if _upsert_suggestion(conn, s, cat, known_set):
                    inserted += 1
            conn.commit()
            _record_usage(conn, Config.ANTHROPIC_MODEL, usage, len(suggestions))
            total_suggested += len(suggestions)
            total_inserted += inserted
            logger.info(
                "category=%s suggested=%d inserted=%d cost=%.5f",
                cat, len(suggestions), inserted, usage.get("est_cost_usd", 0.0),
            )
        msg = f"categories={len(categories)} suggested={total_suggested} inserted={total_inserted}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
