"""Unit tests for the in-process sliding-window auth rate limiter."""
from app.ratelimit import SlidingWindowLimiter, client_ip


def test_allows_up_to_limit_then_blocks():
    lim = SlidingWindowLimiter(max_events=3, window_seconds=60)
    assert lim.hit("ip", now=0) is True
    assert lim.hit("ip", now=1) is True
    assert lim.hit("ip", now=2) is True
    assert lim.hit("ip", now=3) is False


def test_window_slides_old_events_expire():
    lim = SlidingWindowLimiter(max_events=2, window_seconds=10)
    assert lim.hit("ip", now=0) is True
    assert lim.hit("ip", now=1) is True
    assert lim.hit("ip", now=5) is False
    # First event (t=0) leaves the 10s window once now > 10.
    assert lim.hit("ip", now=11) is True


def test_event_exactly_at_window_edge_is_pruned():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=10)
    assert lim.hit("ip", now=0) is True
    # cutoff = now - window = 0; the t=0 event is <= cutoff so it's dropped.
    assert lim.hit("ip", now=10) is True


def test_separate_keys_are_independent():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=60)
    assert lim.hit("a", now=0) is True
    assert lim.hit("b", now=0) is True
    assert lim.hit("a", now=1) is False


def test_reset_single_key_and_all():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=60)
    lim.hit("a", now=0)
    lim.hit("b", now=0)
    lim.reset("a")
    assert lim.hit("a", now=1) is True
    assert lim.hit("b", now=1) is False
    lim.reset()
    assert lim.hit("b", now=2) is True


class _Req:
    def __init__(self, headers=None, remote_addr=None):
        self._h = headers or {}
        self.remote_addr = remote_addr

    @property
    def headers(self):
        h = self._h

        class _H:
            def get(self, k):
                return h.get(k)

        return _H()


def test_client_ip_prefers_forwarded_for_first_hop():
    req = _Req(headers={"X-Forwarded-For": "203.0.113.7, 70.41.3.18"}, remote_addr="10.0.0.1")
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr():
    req = _Req(headers={}, remote_addr="10.0.0.1")
    assert client_ip(req) == "10.0.0.1"


def test_client_ip_unknown_when_nothing_available():
    assert client_ip(_Req(headers={}, remote_addr=None)) == "unknown"
