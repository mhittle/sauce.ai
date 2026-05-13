"""Pure helpers for validating a user-pasted RSS/Atom URL.

Kept Flask-free so they can be unit-tested without dragging in Flask,
auth, or DB stack — same pattern as `app.classifier.*` modules.
"""
import re
from urllib.parse import urlparse

import requests

VALIDATE_TIMEOUT = (5, 10)


def validate_feed(url: str):
    """Return (ok, info_or_error).

    On success, `info` is a dict {"name", "homepage"}.
    On failure, the second element is a user-facing error string.
    """
    if not url or len(url) > 500:
        return False, "Missing or too-long URL."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "URL must be http(s) and include a host."
    try:
        resp = requests.get(
            url,
            timeout=VALIDATE_TIMEOUT,
            headers={"User-Agent": "sauce.ai-news/1.0"},
            allow_redirects=True,
        )
    except requests.RequestException as e:
        return False, f"Couldn't fetch the URL: {e}"
    if resp.status_code >= 400:
        return False, f"Feed returned HTTP {resp.status_code}."
    import feedparser
    parsed_feed = feedparser.parse(resp.content)
    if not parsed_feed.entries:
        return False, "URL doesn't look like an RSS/Atom feed (no entries)."
    title = (getattr(parsed_feed.feed, "title", None) or "").strip()
    if not title:
        title = parsed.netloc
    title = title[:200]
    homepage = (
        getattr(parsed_feed.feed, "link", None)
        or f"{parsed.scheme}://{parsed.netloc}"
    )[:500]
    return True, {"name": title, "homepage": homepage}


def infer_category(name: str, homepage: str) -> str:
    blob = f"{name} {homepage}".lower()
    if re.search(r"\b(tech|verge|wired|ars|techcrunch|hn)\b", blob):
        return "tech"
    if re.search(r"\b(sport|espn|athletic)\b", blob):
        return "sports"
    if re.search(r"\b(business|wsj|bloomberg|ft|reuters)\b", blob):
        return "business"
    if re.search(r"\b(science|nature|sciencemag|scientific)\b", blob):
        return "science"
    if re.search(r"\b(politic|hill|politico|axios)\b", blob):
        return "politics"
    return "general"
