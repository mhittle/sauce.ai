"""In-process sliding-window rate limiter for the auth endpoints.

Thread-safe, zero-infra. Each key (client IP) keeps a deque of recent hit
timestamps; on every hit the window is pruned and the survivor count is
compared against the limit.

v1 limitation (documented in INSTALL.txt §10): counters live in the worker
process, so under a multi-worker Passenger spawn the effective limit is
per-worker, not global. The dominant abuse case — a single script hammering
/auth/login or /auth/signup from one IP — still gets throttled because
LiteSpeed pins a client to a worker for the burst. A DB-backed limiter is
the v2 upgrade if cross-worker accuracy ever matters.
"""

import threading
import time
from collections import defaultdict, deque

_DEFAULT_PROXY_HEADERS = ("X-Forwarded-For", "X-Real-IP")


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float = None) -> bool:
        """Record an attempt for `key`. Returns True if allowed, False if
        the key has exceeded the limit within the window."""
        if now is None:
            now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max_events:
                return False
            dq.append(now)
            return True

    def reset(self, key: str = None):
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


def client_ip(request) -> str:
    """Best-effort client IP behind the LiteSpeed reverse proxy. Uses the
    first hop of X-Forwarded-For, falling back to remote_addr."""
    for header in _DEFAULT_PROXY_HEADERS:
        val = request.headers.get(header)
        if val:
            return val.split(",")[0].strip()
    return request.remote_addr or "unknown"
