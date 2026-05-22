"""Demand-driven classification top-up signal.

The feed serves rows where ``articles.status='classified'``. If a reader
pages faster than the 5-minute ``classify_pending`` cron tick, they hit
the bottom of the classified pool and the feed runs dry.

This module is the in-process side of the fix. On each feed load (HTMX
or full page) the route asks ``maybe_signal_topup``: it counts the
classified rows in the live window, subtracts what the reader has
already consumed, and if the buffer ahead drops below a threshold it
**touches a signal file** (debounced by mtime cooldown). It NEVER forks
or spawns a classifier on the request path — that would violate the
CloudLinux/Passenger nproc ceiling (~115).

A separate every-minute cron entry runs ``classify_pending --triggered-only``
which is a fast no-op unless the signal file is present-and-fresh; when
it is, the script acquires the existing ``job_lock`` and runs normally
(the lock is the inner concurrency guard). The existing 5-min cron stays
as a safety net.

All helpers here are pure (or single-stat-syscall) so they can be unit
tested without a DB or Anthropic.
"""
import os
import time


DEFAULT_THRESHOLD = 400
DEFAULT_COOLDOWN_SECONDS = 60
DEFAULT_SIGNAL_MAX_AGE_SECONDS = 600
DEFAULT_SIGNAL_FILENAME = "classify_topup.signal"


def signal_path_for(app_root, override=None):
    """Resolve the signal file path. Default sits next to the job
    lockfiles in ``<app_root>/logs/``."""
    if override:
        return override
    return os.path.join(app_root, "logs", DEFAULT_SIGNAL_FILENAME)


def buffer_ahead(classified_total, page, page_size):
    """Approximate classified rows remaining ahead of the reader. Global
    (per-user filtering is intentionally ignored — being slightly
    conservative here is fine and avoids a per-user COUNT)."""
    consumed = max(0, int(page)) * max(0, int(page_size))
    return max(0, int(classified_total) - consumed)


def should_trigger(classified_total, pending_total, page, page_size, threshold):
    """Pure: do we want to touch the signal? Buffer-low AND pending pool
    has work to do."""
    if pending_total <= 0:
        return False
    return buffer_ahead(classified_total, page, page_size) < threshold


def _mtime_or_zero(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def cooldown_expired(signal_path, now, cooldown_seconds):
    """Pure-ish: True if the signal file is missing OR its mtime is
    older than ``cooldown_seconds`` ago."""
    return (now - _mtime_or_zero(signal_path)) >= cooldown_seconds


def touch_signal(signal_path):
    """Create/update the signal file's mtime to now. Best-effort —
    swallows OSError so a logs/ permission glitch can't 500 the feed."""
    try:
        os.makedirs(os.path.dirname(signal_path), exist_ok=True)
    except OSError:
        pass
    try:
        with open(signal_path, "a"):
            pass
        os.utime(signal_path, None)
        return True
    except OSError:
        return False


def signal_is_fresh(signal_path, now, max_age_seconds):
    """Cron-side: signal exists AND mtime is within ``max_age_seconds``.
    A stale signal (e.g. lock was held all night) is ignored rather than
    triggering a stampede when the lock finally releases."""
    mtime = _mtime_or_zero(signal_path)
    if mtime == 0.0:
        return False
    return (now - mtime) <= max_age_seconds


def consume_signal(signal_path):
    """Cron-side: remove the signal file. Called inside the job_lock so
    a concurrent feed touch that races us just re-creates it and the
    next 1-min tick acts on it."""
    try:
        os.unlink(signal_path)
        return True
    except OSError:
        return False


def maybe_signal_topup(query_fn, page, page_size, signal_path, *,
                       threshold=DEFAULT_THRESHOLD,
                       cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
                       now=None):
    """Top-level entry point. Returns one of ``"triggered"``,
    ``"buffer_ok"``, ``"no_pending"``, ``"cooldown"`` for callers that
    want to log or test the decision; the feed route ignores the value.

    ``query_fn`` is the app's ``db.query``-style function — passed in
    rather than imported so tests don't need a real DB.
    """
    now = time.time() if now is None else now
    pending = query_fn(
        "SELECT COUNT(*) AS n FROM articles WHERE status='pending'",
        one=True,
    )
    pending_total = (pending["n"] if pending else 0) or 0
    if pending_total <= 0:
        return "no_pending"
    classified = query_fn(
        "SELECT COUNT(*) AS n FROM articles "
        "WHERE status='classified' "
        "AND published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY",
        one=True,
    )
    classified_total = (classified["n"] if classified else 0) or 0
    if not should_trigger(classified_total, pending_total,
                          page, page_size, threshold):
        return "buffer_ok"
    if not cooldown_expired(signal_path, now, cooldown_seconds):
        return "cooldown"
    touch_signal(signal_path)
    return "triggered"
