"""Per-host request throttle shared by every run in the process.

Why: the worker runs several runs at once, each with several conversations in
flight, so one provider key can see 16+ simultaneous requests. Free and
low-tier quotas are a few requests per minute; the provider answers 429 and,
without this, every thread keeps hammering until the run aborts.

Two mechanisms, both keyed by the request's host (so the Gemini target, the
Gemini attacker and the Gemini judge share one budget):

- a **token bucket** at ``rpm`` requests per minute when the host has a
  configured limit (``REDTEAM_RPM_LIMITS``), smoothing bursts;
- a **shared penalty**: when any caller receives a 429, every caller on that
  host waits out the server's Retry-After (or the backoff) before sending,
  instead of each discovering the limit on its own.

Hosts without a configured limit (the default) are not metered but still
share penalties, which is enough once a key is on a paid tier.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

# No host is metered by default: paid tiers allow hundreds of requests a minute
# and the shared 429 penalty adapts on its own. Set REDTEAM_RPM_LIMITS for a
# key on a free tier, e.g. "generativelanguage.googleapis.com=10".
DEFAULT_LIMITS = ""


def parse_limits(spec: str) -> dict[str, float]:
    """``"host=rpm,host=rpm"`` → {host: rpm}; bad entries ignored, 0 disables."""
    out: dict[str, float] = {}
    for part in (spec or "").split(","):
        if "=" not in part:
            continue
        host, _, v = part.partition("=")
        try:
            rpm = float(v)
        except ValueError:
            continue
        host = host.strip().lower()
        if host and rpm > 0:
            out[host] = rpm
    return out


class HostLimiter:
    def __init__(self, rpm: float | None, clock=None, sleep=None) -> None:
        self.rpm = rpm if rpm and rpm > 0 else None
        # resolved at call time so tests can patch time.sleep after construction
        self._clock = clock or (lambda: time.monotonic())
        self._sleep = sleep or (lambda s: time.sleep(s))
        self._lock = threading.Lock()
        self._next_slot = 0.0          # earliest time the next token is free
        self._blocked_until = 0.0      # shared penalty after a 429
        self.waits = 0                 # calls that had to wait (for status/debug)
        self.penalties = 0

    def acquire(self) -> float:
        """Block until this caller may send; returns the seconds it waited."""
        with self._lock:
            now = self._clock()
            start = max(now, self._blocked_until)
            if self.rpm:
                start = max(start, self._next_slot)
                self._next_slot = start + 60.0 / self.rpm
            wait = start - now
            if wait > 0:
                self.waits += 1
        if wait > 0:
            self._sleep(wait)
        return max(0.0, wait)

    def penalize(self, seconds: float) -> None:
        """A 429 arrived: hold every caller on this host for ``seconds``."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + max(0.0, seconds))
            self.penalties += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {"rpm": self.rpm, "waits": self.waits, "penalties": self.penalties,
                    "blocked_for_s": max(0.0, self._blocked_until - self._clock())}


class Registry:
    def __init__(self, limits: dict[str, float] | None = None) -> None:
        self.limits = dict(limits or {})
        self._by_host: dict[str, HostLimiter] = {}
        self._lock = threading.Lock()

    def for_url(self, url: str) -> HostLimiter:
        host = (urlparse(url).netloc or url).lower()
        with self._lock:
            lim = self._by_host.get(host)
            if lim is None:
                lim = self._by_host[host] = HostLimiter(self.limits.get(host))
            return lim

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {h: l.snapshot() for h, l in self._by_host.items()}


_REGISTRY: Registry | None = None
_RLOCK = threading.Lock()


def registry(settings=None) -> Registry:
    """The process-wide registry, created from ``settings.rpm_limits`` on first use."""
    global _REGISTRY
    with _RLOCK:
        if _REGISTRY is None:
            spec = getattr(settings, "rpm_limits", None)
            _REGISTRY = Registry(parse_limits(spec if spec is not None else DEFAULT_LIMITS))
        return _REGISTRY


def reset_for_tests() -> None:
    global _REGISTRY
    with _RLOCK:
        _REGISTRY = None
