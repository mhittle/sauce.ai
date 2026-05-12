"""Active per-article paywall detection.

`detect_paywall(url)` fetches the article URL and returns a 0..1 score.
Run during `classify_pending`. Network failures and bot-blocks return
0.5 ("suspected") rather than 0.0 — sites that won't let us in get
treated as walled by default. See roadmap.md "Paywall feature".
"""
import re

import requests

UA = "Mozilla/5.0 (compatible; sauce.ai-news/1.0; +https://sauce.ai)"

# Cap downloaded body so a giant page doesn't blow the cron budget.
MAX_BODY_BYTES = 256 * 1024

# Phrases that strongly imply a wall when paired with a truncated body.
PAYWALL_PHRASES = (
    "subscribe to read",
    "subscribe to continue",
    "subscribers only",
    "for subscribers only",
    "this article is for subscribers",
    "create a free account to continue",
    "create a free account to read",
    "register to continue",
    "sign up to continue",
    "log in to continue reading",
    "members-only",
    "subscribe now to read",
    "to continue reading, subscribe",
    "this content is reserved for",
)

_JSONLD_FALSE = re.compile(r'"isaccessibleforfree"\s*:\s*false', re.I)
_CONTENT_TIER = re.compile(
    r'<meta[^>]+(?:property|name)\s*=\s*["\']article:content[_-]tier["\']'
    r'[^>]+content\s*=\s*["\']([^"\']+)',
    re.I,
)

# "Blocked / can't verify" sentinel. Per product direction, treat as suspected.
SUSPECTED = 0.5


def detect_paywall(url, *, timeout=8.0, session=None):
    """Return paywall score for an article URL.

    1.0 — explicit subscription-required signal (JSON-LD or content_tier=locked/paid).
    0.8 — paywall phrase appears on a short body (<8KB).
    0.6 — content_tier=metered.
    0.5 — blocked / 4xx / 5xx / timeout / short body with no phrase.
    0.0 — body fetched, no paywall signals.
    """
    if not url:
        return SUSPECTED
    sess = session or requests
    try:
        resp = sess.get(
            url,
            timeout=(min(5.0, timeout), timeout),
            headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"},
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException:
        return SUSPECTED
    try:
        try:
            raw = resp.raw.read(MAX_BODY_BYTES, decode_content=True) or b""
        except Exception:
            return SUSPECTED
        status = resp.status_code
    finally:
        resp.close()

    if status in (401, 402, 403, 451) or status >= 400:
        return SUSPECTED

    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
    lower = text.lower()

    if _JSONLD_FALSE.search(lower):
        return 1.0

    m = _CONTENT_TIER.search(text)
    if m:
        tier = m.group(1).strip().lower()
        if tier in ("locked", "paid", "subscriber", "subscription"):
            return 1.0
        if tier == "metered":
            return 0.6

    body_size = len(text)
    if body_size < 8 * 1024 and any(p in lower for p in PAYWALL_PHRASES):
        return 0.8

    if body_size < 1500:
        return SUSPECTED

    return 0.0
