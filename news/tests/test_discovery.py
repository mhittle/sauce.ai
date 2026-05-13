"""Unit tests for the source-discovery helpers and pure functions.

We exercise:
- `app.discovery.extract_domain` — normalization rules
- `app.discovery.discover_feed_url` — RSS auto-discovery flow against a
  scripted fake session (no network)
- `app.discovery.extract_urls` — URL fishing from free-form LLM output
- `jobs/discover_harvest.count_new_domains` — pure dedup/filter logic
- `jobs/discover_llm.parse_llm_response` — JSON parsing and fallback

The cron entry points (`main`) are not exercised here; their behavior is
covered indirectly via the pure helpers they wrap. Integration with the
actual DB is out of scope for unit tests.
"""
import os
import sys
import types

import pytest


# The job scripts are not a package, so we have to walk in via sys.path.
HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.normpath(os.path.join(HERE, "..", "jobs"))
if JOBS_DIR not in sys.path:
    sys.path.insert(0, JOBS_DIR)


@pytest.fixture(autouse=True)
def _stub_feedparser(monkeypatch):
    """The CI sandbox can't build feedparser (sgmllib3k); stub it so the
    discovery module's lazy import resolves. Each test that needs to
    control feed-parsing behavior overrides via the returned state."""
    stub = types.ModuleType("feedparser")
    state = {"entries": [], "title": "", "link": ""}

    def _parse(_content):
        return types.SimpleNamespace(
            entries=list(state["entries"]),
            feed=types.SimpleNamespace(title=state["title"], link=state["link"]),
        )

    stub.parse = _parse
    monkeypatch.setitem(sys.modules, "feedparser", stub)
    return state


# ---------------------------------------------------------------------------
# extract_domain
# ---------------------------------------------------------------------------

from app.discovery import (  # noqa: E402
    extract_domain,
    extract_urls,
    discover_feed_url,
    try_feed_url,
    DOMAIN_BLOCKLIST,
)


def test_extract_domain_strips_www_and_lowercases():
    assert extract_domain("https://WWW.Example.com/path") == "example.com"


def test_extract_domain_drops_port():
    assert extract_domain("http://example.com:8080/x") == "example.com"


def test_extract_domain_handles_subdomain():
    assert extract_domain("https://news.bbc.co.uk/world") == "news.bbc.co.uk"


def test_extract_domain_returns_none_for_blocklisted():
    for d in ("https://youtube.com/foo", "https://twitter.com/bar"):
        assert extract_domain(d) is None


def test_extract_domain_returns_none_for_bare_word():
    assert extract_domain("not a url") is None


def test_extract_domain_returns_none_for_empty():
    assert extract_domain("") is None
    assert extract_domain(None) is None


# ---------------------------------------------------------------------------
# extract_urls
# ---------------------------------------------------------------------------

def test_extract_urls_pulls_from_markdown():
    text = "* [Outlet](https://outlet.example/rss) — note\n* https://b.example/feed"
    found = extract_urls(text)
    assert "https://outlet.example/rss" in found
    assert "https://b.example/feed" in found


def test_extract_urls_empty():
    assert extract_urls("") == []
    assert extract_urls(None) == []


# ---------------------------------------------------------------------------
# discover_feed_url
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, content=b"", status=200, final_url=None):
        self.content = content
        self.status_code = status
        self.url = final_url or ""


class _ScriptedSession:
    """A fake requests.Session that returns canned responses keyed by
    the exact URL passed to .get(). Anything missing raises so tests
    fail loudly instead of silently going to network."""

    def __init__(self, routes):
        # routes: dict[url] = _Resp or Exception
        self.routes = dict(routes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        resp = self.routes.get(url)
        if resp is None:
            # Common-paths probe — default to 404 so callers don't have
            # to script every path individually.
            return _Resp(b"", 404, final_url=url)
        if isinstance(resp, Exception):
            raise resp
        if not resp.url:
            resp.url = url
        return resp


def _feed_bytes():
    # Trivial RSS — the stubbed feedparser parses based on `state` not bytes
    return b"<rss><channel><item><title>x</title></item></channel></rss>"


def test_discover_feed_url_hits_common_path(_stub_feedparser):
    _stub_feedparser["entries"] = [{"title": "post"}]
    _stub_feedparser["title"] = "Example Feed"
    _stub_feedparser["link"] = "https://example.com"
    sess = _ScriptedSession({
        "https://example.com/feed": _Resp(_feed_bytes(), 200),
    })
    hit = discover_feed_url("example.com", session=sess)
    assert hit is not None
    assert hit["feed_url"] == "https://example.com/feed"
    assert hit["name"] == "Example Feed"


def test_discover_feed_url_falls_back_to_link_alternate(_stub_feedparser):
    _stub_feedparser["entries"] = [{"title": "post"}]
    _stub_feedparser["title"] = "Alt Feed"
    homepage_html = (
        b'<html><head>'
        b'<link rel="alternate" type="application/rss+xml" '
        b'href="/curated.xml" title="Curated"/>'
        b'</head><body></body></html>'
    )
    sess = _ScriptedSession({
        "https://news.example.com/": _Resp(homepage_html, 200),
        "https://news.example.com/curated.xml": _Resp(_feed_bytes(), 200),
    })
    hit = discover_feed_url("news.example.com", session=sess)
    assert hit is not None
    assert hit["feed_url"].endswith("/curated.xml")


def test_discover_feed_url_none_when_nothing_matches(_stub_feedparser):
    # Empty routes => default 404 for every probe. Homepage 404 means no
    # HTML to parse for alternates, so we run out of options.
    _stub_feedparser["entries"] = [{"title": "x"}]
    sess = _ScriptedSession({})
    assert discover_feed_url("dead.example", session=sess) is None


def test_try_feed_url_rejects_4xx(_stub_feedparser):
    _stub_feedparser["entries"] = [{"title": "x"}]
    sess = _ScriptedSession({"https://example.com/feed": _Resp(b"", 500)})
    assert try_feed_url(sess, "https://example.com/feed") is None


def test_try_feed_url_rejects_empty_feed(_stub_feedparser):
    _stub_feedparser["entries"] = []
    sess = _ScriptedSession({"https://example.com/feed": _Resp(b"<rss/>", 200)})
    assert try_feed_url(sess, "https://example.com/feed") is None


# ---------------------------------------------------------------------------
# discover_harvest.count_new_domains
# ---------------------------------------------------------------------------

def test_count_new_domains_dedups_and_filters():
    import discover_harvest as dh
    urls = [
        "https://example.com/article-1",
        "https://example.com/article-2",
        "https://www.bbc.com/news/world-1",  # already known
        "https://www.bbc.com/news/world-2",  # already known
        "https://blacklisted.example/x",      # decided
        "https://newoutlet.test/post",
        "not a url",
        "https://youtube.com/video",          # blocklisted in extract_domain
    ]
    known = {"bbc.com"}
    decided = {"blacklisted.example"}
    counts = dh.count_new_domains(urls, known, decided)
    assert counts == {"example.com": 2, "newoutlet.test": 1}


def test_count_new_domains_empty_inputs():
    import discover_harvest as dh
    assert dh.count_new_domains([], set(), set()) == {}
    assert dh.count_new_domains(["not a url"], set(), set()) == {}


# ---------------------------------------------------------------------------
# discover_llm.parse_llm_response
# ---------------------------------------------------------------------------

def test_parse_llm_response_strict_json():
    import discover_llm as dl
    text = (
        '{"suggestions": ['
        '{"name": "Outlet A", "feed_url": "https://a.example/feed", "why": "n/a"},'
        '{"name": "Outlet B", "feed_url": "https://b.example/rss", "why": "n/a"}'
        ']}'
    )
    out = dl.parse_llm_response(text)
    assert len(out) == 2
    assert out[0]["feed_url"] == "https://a.example/feed"


def test_parse_llm_response_with_code_fence():
    import discover_llm as dl
    text = (
        '```json\n'
        '{"suggestions": [{"name": "X", "feed_url": "https://x.test/rss", "why": "y"}]}\n'
        '```'
    )
    out = dl.parse_llm_response(text)
    assert len(out) == 1
    assert out[0]["feed_url"] == "https://x.test/rss"


def test_parse_llm_response_fallback_to_url_fishing():
    import discover_llm as dl
    text = (
        "I'm not sure I can return JSON, but here are some feeds:\n"
        "- https://outlet1.example/rss\n"
        "- https://outlet2.example/feed.xml"
    )
    out = dl.parse_llm_response(text)
    urls = [s["feed_url"] for s in out]
    assert "https://outlet1.example/rss" in urls
    assert "https://outlet2.example/feed.xml" in urls


def test_parse_llm_response_empty():
    import discover_llm as dl
    assert dl.parse_llm_response("") == []
    assert dl.parse_llm_response(None) == []


def test_parse_llm_response_skips_entries_without_feed_url():
    import discover_llm as dl
    text = '{"suggestions": [{"name": "no url", "why": "nope"}]}'
    assert dl.parse_llm_response(text) == []
