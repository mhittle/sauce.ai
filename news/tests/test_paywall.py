import io

import requests

from app.classifier.paywall import detect_paywall, SUSPECTED


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


def _filler(n_chars):
    return ("a " * (n_chars // 2)).encode("utf-8")


def test_returns_one_for_jsonld_not_accessible_for_free():
    body = b'<html><script type="application/ld+json">{"isAccessibleForFree": false}</script></html>'
    sess = _FakeSession(_FakeResp(body=body + _filler(20000)))
    assert detect_paywall("https://x.test/a", session=sess) == 1.0


def test_returns_one_for_content_tier_locked():
    body = b'<html><meta property="article:content_tier" content="locked"></html>' + _filler(20000)
    sess = _FakeSession(_FakeResp(body=body))
    assert detect_paywall("https://x.test/a", session=sess) == 1.0


def test_returns_point6_for_metered():
    body = b'<html><meta name="article:content_tier" content="metered"></html>' + _filler(20000)
    sess = _FakeSession(_FakeResp(body=body))
    assert detect_paywall("https://x.test/a", session=sess) == 0.6


def test_returns_point8_for_paywall_phrase_on_short_body():
    body = b"<html>Subscribe to read the full article.</html>"  # tiny body
    sess = _FakeSession(_FakeResp(body=body))
    assert detect_paywall("https://x.test/a", session=sess) == 0.8


def test_phrase_on_long_body_does_not_flag():
    body = b"<html>Subscribe to read.</html>" + _filler(20000)
    sess = _FakeSession(_FakeResp(body=body))
    assert detect_paywall("https://x.test/a", session=sess) == 0.0


def test_returns_zero_for_clean_long_body():
    body = b"<html><p>" + _filler(20000) + b"</p></html>"
    sess = _FakeSession(_FakeResp(body=body))
    assert detect_paywall("https://x.test/a", session=sess) == 0.0


def test_returns_suspected_for_short_body_no_phrase():
    body = b"<html>tiny</html>"
    sess = _FakeSession(_FakeResp(body=body))
    assert detect_paywall("https://x.test/a", session=sess) == SUSPECTED


def test_returns_suspected_for_4xx():
    sess = _FakeSession(_FakeResp(body=_filler(20000), status=403))
    assert detect_paywall("https://x.test/a", session=sess) == SUSPECTED


def test_returns_suspected_for_connection_error():
    sess = _FakeSession(exc=requests.ConnectionError("boom"))
    assert detect_paywall("https://x.test/a", session=sess) == SUSPECTED


def test_returns_suspected_for_timeout():
    sess = _FakeSession(exc=requests.Timeout("slow"))
    assert detect_paywall("https://x.test/a", session=sess) == SUSPECTED


def test_returns_suspected_for_empty_url():
    assert detect_paywall("", session=_FakeSession()) == SUSPECTED
    assert detect_paywall(None, session=_FakeSession()) == SUSPECTED


def test_passes_user_agent_header():
    body = b"<html>" + _filler(20000) + b"</html>"
    sess = _FakeSession(_FakeResp(body=body))
    detect_paywall("https://x.test/a", session=sess)
    assert "User-Agent" in sess.last_kwargs["headers"]
    assert "sauce.ai" in sess.last_kwargs["headers"]["User-Agent"]
