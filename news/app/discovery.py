"""Pure helpers for the source-discovery pipeline.

Kept Flask-free so the cron jobs and tests can import them without
spinning up the app. Mirrors the pattern used by `app.feed_validation`
and `app.classifier.*`.

Two responsibilities:

1. `extract_domain(url)` — normalize a URL to a bare hostname suitable
   for keying the `candidate_sources` table (lower-cased, no `www.`,
   no port, no path).
2. `discover_feed_url(domain, *, session)` — given a bare domain, find
   the canonical RSS/Atom feed URL by trying common paths and parsing
   `<link rel="alternate">` tags on the homepage. Returns
   {"feed_url", "name", "homepage"} on success or None on failure.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse, urljoin


HTTP_TIMEOUT = (5, 10)
USER_AGENT = "sauce.ai-news/1.0 (+discovery)"

COMMON_FEED_PATHS = (
    "/feed",
    "/rss",
    "/feed.xml",
    "/rss.xml",
    "/atom.xml",
    "/feed/",
    "/feeds/posts/default",
    "/index.xml",
)

FEED_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
)

DOMAIN_BLOCKLIST = frozenset({
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
    "imgur.com",
    "i.redd.it",
    "v.redd.it",
    "github.com",
    "wikipedia.org",
    "amazon.com",
    "ebay.com",
})


def extract_domain(url: str) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except ValueError:
        return None
    host = (parsed.netloc or "").lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    if host in DOMAIN_BLOCKLIST:
        return None
    return host


class _LinkAlternateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feeds: list[tuple[str, str]] = []  # (href, title)
        self._in_head = False
        self._head_done = False

    def handle_starttag(self, tag, attrs):
        if self._head_done:
            return
        if tag == "head":
            self._in_head = True
            return
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        ctype = a.get("type", "").lower()
        if "alternate" not in rel:
            return
        if ctype not in FEED_CONTENT_TYPES:
            return
        href = a.get("href", "").strip()
        if href:
            self.feeds.append((href, a.get("title", "")))

    def handle_endtag(self, tag):
        if tag == "head":
            self._head_done = True
            self._in_head = False


def _looks_like_feed(content: bytes) -> bool:
    try:
        import feedparser
    except ImportError:
        head = content[:512].lower()
        return b"<rss" in head or b"<feed" in head or b"<atom" in head
    parsed = feedparser.parse(content)
    return bool(parsed.entries)


def _fetch_feed_metadata(content: bytes, fallback_homepage: str):
    """Pull (name, homepage) out of a feed payload. Doesn't fail."""
    name = ""
    homepage = fallback_homepage
    try:
        import feedparser
        parsed = feedparser.parse(content)
        name = (getattr(parsed.feed, "title", None) or "").strip()
        link = (getattr(parsed.feed, "link", None) or "").strip()
        if link:
            homepage = link
    except Exception:
        pass
    return name[:200], homepage[:500]


def try_feed_url(session, feed_url: str):
    """GET feed_url, confirm it parses as a feed. Returns
    {"feed_url", "name", "homepage"} or None."""
    try:
        resp = session.get(
            feed_url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
    except Exception:
        return None
    if resp.status_code >= 400:
        return None
    body = resp.content or b""
    if not body:
        return None
    if not _looks_like_feed(body):
        return None
    parsed = urlparse(resp.url)
    fallback_home = f"{parsed.scheme}://{parsed.netloc}"
    name, homepage = _fetch_feed_metadata(body, fallback_home)
    if not name:
        name = parsed.netloc
    return {"feed_url": resp.url[:1024], "name": name, "homepage": homepage}


def _parse_alternate_links(html_bytes: bytes, base_url: str):
    try:
        html = html_bytes.decode("utf-8", errors="replace")
    except Exception:
        return []
    parser = _LinkAlternateParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    out = []
    for href, _title in parser.feeds:
        absolute = urljoin(base_url, href)
        out.append(absolute)
    return out


def discover_feed_url(domain: str, *, session) -> Optional[dict]:
    """Find the canonical RSS/Atom feed for `domain`. Tries common
    well-known paths first (cheap), then falls back to parsing the
    homepage HTML for <link rel="alternate" type="application/rss+xml">.

    Returns dict {"feed_url", "name", "homepage"} on success, or None.
    """
    if not domain:
        return None

    for scheme in ("https", "http"):
        for path in COMMON_FEED_PATHS:
            feed_url = f"{scheme}://{domain}{path}"
            hit = try_feed_url(session, feed_url)
            if hit:
                return hit

        homepage_url = f"{scheme}://{domain}/"
        try:
            resp = session.get(
                homepage_url,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
        except Exception:
            continue
        if resp.status_code >= 400:
            continue
        for absolute in _parse_alternate_links(resp.content or b"", resp.url):
            hit = try_feed_url(session, absolute)
            if hit:
                return hit
        # Found the homepage but no feed link; no need to retry http after https.
        break

    return None


_URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    """Pull bare http(s) URLs out of an LLM response. Tolerates whatever
    free-form format Claude returns (markdown links, bullet lists, plain
    URLs) since we only need the URL itself."""
    if not text:
        return []
    return _URL_RE.findall(text)
