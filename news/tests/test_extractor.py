import sys
import types

import requests

from app import extractor
from app.extractor import extract_body


class _FakeRaw:
    def __init__(self, data):
        self._data = data

    def read(self, n, decode_content=True):
        return self._data[:n]


class _FakeResp:
    def __init__(self, body=b"", status=200):
        self.raw = _FakeRaw(body)
        self.status_code = status

    def close(self):
        pass


class _FakeSession:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.last_url = None
        self.last_kwargs = None

    def get(self, url, **kwargs):
        self.last_url = url
        self.last_kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        return self._resp


def _stub_trafilatura(monkeypatch, *, text=None, body_html=None, author=None, image=None, raises=False):
    """Inject a fake trafilatura module so we don't need it installed for tests."""
    mod = types.ModuleType("trafilatura")

    def _extract(html, **kwargs):
        if raises:
            raise RuntimeError("boom")
        return body_html if kwargs.get("output_format") == "html" else text

    def _extract_metadata(html):
        if author is None and image is None:
            return None
        meta = types.SimpleNamespace(author=author, image=image)
        return meta

    mod.extract = _extract
    mod.extract_metadata = _extract_metadata
    monkeypatch.setitem(sys.modules, "trafilatura", mod)


def _long_text(n_words=200):
    return " ".join(["story"] * n_words)


def test_returns_ok_on_clean_extract(monkeypatch):
    _stub_trafilatura(monkeypatch, text=_long_text(), body_html="<p>story</p>",
                      author="Jane Doe", image="https://cdn.example/i.jpg")
    sess = _FakeSession(_FakeResp(body=b"<html>plenty of body</html>"))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "ok"
    assert out["word_count"] >= extractor.MIN_WORDS
    assert out["author"] == "Jane Doe"
    assert out["lead_image"] == "https://cdn.example/i.jpg"
    assert out["body_text"].startswith("story")


def test_returns_empty_when_extract_yields_nothing(monkeypatch):
    _stub_trafilatura(monkeypatch, text=None, body_html=None)
    sess = _FakeSession(_FakeResp(body=b"<html>noise</html>"))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "empty"
    assert out["body_text"] is None
    assert out["word_count"] == 0


def test_returns_empty_when_below_min_words(monkeypatch):
    _stub_trafilatura(monkeypatch, text="too short", body_html="<p>too short</p>")
    sess = _FakeSession(_FakeResp(body=b"<html>x</html>"))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "empty"


def test_returns_blocked_on_4xx(monkeypatch):
    _stub_trafilatura(monkeypatch, text=_long_text())
    sess = _FakeSession(_FakeResp(body=b"forbidden", status=403))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "blocked"
    assert out["body_text"] is None


def test_returns_error_on_connection_error(monkeypatch):
    _stub_trafilatura(monkeypatch, text=_long_text())
    sess = _FakeSession(exc=requests.ConnectionError("boom"))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "error"


def test_returns_error_on_timeout(monkeypatch):
    _stub_trafilatura(monkeypatch, text=_long_text())
    sess = _FakeSession(exc=requests.Timeout("slow"))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "error"


def test_returns_error_on_trafilatura_exception(monkeypatch):
    _stub_trafilatura(monkeypatch, raises=True)
    sess = _FakeSession(_FakeResp(body=b"<html>x</html>"))
    out = extract_body("https://x.test/a", session=sess)
    assert out["status"] == "error"


def test_returns_error_for_empty_url(monkeypatch):
    out = extract_body("", session=_FakeSession())
    assert out["status"] == "error"
    out = extract_body(None, session=_FakeSession())
    assert out["status"] == "error"


def test_passes_user_agent_header(monkeypatch):
    _stub_trafilatura(monkeypatch, text=_long_text())
    sess = _FakeSession(_FakeResp(body=b"<html>x</html>"))
    extract_body("https://x.test/a", session=sess)
    assert "User-Agent" in sess.last_kwargs["headers"]
    assert "sauce.ai" in sess.last_kwargs["headers"]["User-Agent"]


def test_collapses_whitespace(monkeypatch):
    _stub_trafilatura(monkeypatch, text="word " * 80 + "\n\n\n  extra")
    sess = _FakeSession(_FakeResp(body=b"<html>x</html>"))
    out = extract_body("https://x.test/a", session=sess)
    assert "  " not in out["body_text"]
    assert "\n" not in out["body_text"]
