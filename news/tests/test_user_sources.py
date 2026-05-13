"""Tests for user-added RSS feed validation.

We stub `feedparser` and `requests.get` so these tests don't depend on
network or on the local sandbox's feedparser/sgmllib compatibility.
"""
import sys
import types

import pytest
import requests


class _FakeFeed:
    def __init__(self, entries, title="", link=""):
        self.entries = entries
        self.feed = types.SimpleNamespace(title=title, link=link)


@pytest.fixture(autouse=True)
def _fake_feedparser(monkeypatch):
    """Inject a stub `feedparser` module so tests work even when the
    real feedparser package is missing (sandbox) or environment-broken.
    Tests parametrize behavior via the `feed_payload` fixture below."""
    stub = types.ModuleType("feedparser")
    state = {"feed": _FakeFeed(entries=[])}

    def _parse(_content):
        return state["feed"]

    stub.parse = _parse
    monkeypatch.setitem(sys.modules, "feedparser", stub)
    return state


@pytest.fixture
def feed_payload(_fake_feedparser):
    def _set(entries=None, title="", link=""):
        _fake_feedparser["feed"] = _FakeFeed(
            entries=entries or [], title=title, link=link
        )
    return _set


class _Resp:
    def __init__(self, content=b"", status=200):
        self.content = content
        self.status_code = status


def _patch_requests_get(monkeypatch, *, resp=None, exc=None):
    def fake_get(url, **kwargs):
        if exc is not None:
            raise exc
        return resp
    monkeypatch.setattr(requests, "get", fake_get)


from app.feed_validation import validate_feed as _validate_feed, infer_category as _infer_category  # noqa: E402


def test_validate_feed_happy_path(monkeypatch, feed_payload):
    feed_payload(entries=[{"title": "post 1"}, {"title": "post 2"}],
                 title="Example Feed", link="https://example.com")
    _patch_requests_get(monkeypatch, resp=_Resp(b"<rss/>", 200))
    ok, info = _validate_feed("https://example.com/feed.xml")
    assert ok is True
    assert info["name"] == "Example Feed"
    assert info["homepage"] == "https://example.com"


def test_validate_feed_falls_back_to_netloc_when_no_title(monkeypatch, feed_payload):
    feed_payload(entries=[{"title": "post"}], title="", link="")
    _patch_requests_get(monkeypatch, resp=_Resp(b"<rss/>", 200))
    ok, info = _validate_feed("https://foo.example.com/feed")
    assert ok is True
    assert info["name"] == "foo.example.com"
    assert info["homepage"].startswith("https://foo.example.com")


def test_validate_feed_rejects_non_http_scheme(monkeypatch, feed_payload):
    feed_payload(entries=[{"title": "x"}])
    _patch_requests_get(monkeypatch, resp=_Resp(b"<rss/>", 200))
    ok, err = _validate_feed("ftp://example.com/feed.xml")
    assert ok is False
    assert "http" in err.lower()


def test_validate_feed_rejects_empty_url():
    ok, _ = _validate_feed("")
    assert ok is False


def test_validate_feed_rejects_long_url():
    ok, _ = _validate_feed("https://" + "a" * 600 + ".example.com/feed")
    assert ok is False


def test_validate_feed_rejects_4xx(monkeypatch, feed_payload):
    feed_payload(entries=[])
    _patch_requests_get(monkeypatch, resp=_Resp(b"not found", 404))
    ok, err = _validate_feed("https://example.com/missing.xml")
    assert ok is False
    assert "404" in err


def test_validate_feed_rejects_request_exception(monkeypatch, feed_payload):
    _patch_requests_get(monkeypatch, exc=requests.ConnectionError("dns fail"))
    ok, err = _validate_feed("https://example.com/feed.xml")
    assert ok is False
    assert "fetch" in err.lower()


def test_validate_feed_rejects_zero_entries(monkeypatch, feed_payload):
    feed_payload(entries=[], title="Empty")
    _patch_requests_get(monkeypatch, resp=_Resp(b"<rss/>", 200))
    ok, err = _validate_feed("https://empty.example.com/feed.xml")
    assert ok is False
    assert "entries" in err.lower() or "rss" in err.lower() or "atom" in err.lower()


def test_infer_category_tech():
    assert _infer_category("Ars Technica", "https://arstechnica.com") == "tech"


def test_infer_category_business():
    assert _infer_category("Bloomberg Markets", "https://bloomberg.com") == "business"


def test_infer_category_falls_back_to_general():
    assert _infer_category("Random Blog", "https://example.com") == "general"
