"""Pure helpers for breaking-news alert detection.

Kept Flask-free / DB-free / SMTP-free / Haiku-free so the unit tests
(``tests/test_breaking.py``) can import them without spinning up the app.
Mirrors the pattern used by ``app.feed_diversify`` / ``app.trending`` /
``app.discussion``.

The cron job ``jobs/breaking_alerts.py`` is the orchestrator: query →
these helpers → LLM gate → mailer. Each helper handles exactly one
decision so the failure modes of the send path stay easy to reason about.
"""
from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional


def select_candidates(rows: Iterable[Mapping], min_outlets: int) -> list[dict]:
    """Keep only outlet-burst rows that meet the minimum distinct-outlet floor.

    ``rows`` is an iterable of mappings with ``outlet_count`` (int) and a
    ``story_id``. Rows whose ``outlet_count`` is missing or non-numeric
    are dropped silently. Input order is preserved.
    """
    out: list[dict] = []
    for r in rows:
        try:
            n = int(r.get("outlet_count"))
        except (TypeError, ValueError):
            continue
        if n >= min_outlets:
            out.append(dict(r))
    return out


def is_suppressed(event_text: Optional[str], mute_terms: Iterable[str]) -> bool:
    """Return True iff the event text matches any user mute term.

    Matching mirrors ``app.term_prefs._MATCH_EXPR``: case-insensitive
    plain substring against the event text. ``mute_terms`` is expected
    to already be normalized (see ``app.term_prefs.normalize_term``).
    """
    if not event_text or not mute_terms:
        return False
    haystack = event_text.lower()
    for term in mute_terms:
        if not term:
            continue
        if term in haystack:
            return True
    return False


def daily_cap_ok(prefs_row: Optional[Mapping], max_per_day: int, today) -> bool:
    """Return True iff another alert may be sent to this user today (UTC).

    ``prefs_row`` is a mapping with ``alerts_day`` (date or None) and
    ``alerts_today`` (int). A row whose ``alerts_day`` is None or an
    earlier date is treated as a clean slate. ``max_per_day <= 0``
    disables sending entirely.
    """
    if max_per_day <= 0:
        return False
    if not prefs_row:
        return True
    day = prefs_row.get("alerts_day")
    if day != today:
        return True
    count = prefs_row.get("alerts_today") or 0
    return count < max_per_day


def parse_llm_verdict(text: Optional[str]) -> Optional[dict]:
    """Parse the Haiku gate's JSON response into a clamped verdict dict.

    Expected shape: ``{"is_major": bool, "headline": str, "blurb": str}``.
    Tolerates a leading triple-backtick ``json`` fence (matches the
    convention in ``classify_batch_llm``). Returns None on any parse failure or
    non-object payload — the caller treats that as "no send" and records
    the story as rejected so the next 15-min tick does not re-judge it.

    Trims/clamps ``headline`` to 200 chars and ``blurb`` to 500 chars so
    the verdict fits the ``breaking_news_alerts`` and email templates.
    """
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        parsed = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    headline = str(parsed.get("headline") or "").strip()[:200]
    blurb = str(parsed.get("blurb") or "").strip()[:500]
    return {
        "is_major": bool(parsed.get("is_major")),
        "headline": headline,
        "blurb": blurb,
    }
