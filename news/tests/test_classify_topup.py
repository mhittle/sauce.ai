"""Unit tests for the demand-driven classify top-up signal.

The pure helpers in ``app.classify_topup`` decide WHETHER to touch the
signal; the cron script's ``--triggered-only`` mode decides whether to
act on it. None of this should require a DB or Anthropic — the tests
fake the query function and the filesystem with tmp paths.
"""
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (HERE, os.path.join(HERE, "jobs")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app import classify_topup  # noqa: E402


# --- buffer_ahead ----------------------------------------------------------

def test_buffer_ahead_basic():
    assert classify_topup.buffer_ahead(1000, page=1, page_size=40) == 960
    assert classify_topup.buffer_ahead(1000, page=10, page_size=40) == 600
    assert classify_topup.buffer_ahead(1000, page=25, page_size=40) == 0


def test_buffer_ahead_never_negative():
    assert classify_topup.buffer_ahead(100, page=10, page_size=40) == 0


# --- should_trigger --------------------------------------------------------

def test_should_trigger_low_buffer():
    # 200 classified, page 1, 40/page -> ahead=160 < 400 -> trigger.
    assert classify_topup.should_trigger(
        classified_total=200, pending_total=50,
        page=1, page_size=40, threshold=400) is True


def test_should_trigger_buffer_ok():
    # 1000 classified, page 1 -> ahead=960 >= 400 -> no trigger.
    assert classify_topup.should_trigger(
        classified_total=1000, pending_total=50,
        page=1, page_size=40, threshold=400) is False


def test_should_trigger_no_pending():
    # Buffer is low but nothing to classify -> no trigger (we'd just
    # touch a file the cron can't act on).
    assert classify_topup.should_trigger(
        classified_total=0, pending_total=0,
        page=1, page_size=40, threshold=400) is False


# --- cooldown_expired / touch / fresh / consume ----------------------------

def test_cooldown_expired_missing_file(tmp_path):
    path = str(tmp_path / "missing.signal")
    assert classify_topup.cooldown_expired(path, now=time.time(), cooldown_seconds=60) is True


def test_cooldown_expired_recent(tmp_path):
    path = str(tmp_path / "fresh.signal")
    classify_topup.touch_signal(path)
    assert classify_topup.cooldown_expired(path, now=time.time(), cooldown_seconds=60) is False


def test_cooldown_expired_old(tmp_path):
    path = str(tmp_path / "old.signal")
    classify_topup.touch_signal(path)
    old = time.time() - 7200
    os.utime(path, (old, old))
    assert classify_topup.cooldown_expired(path, now=time.time(), cooldown_seconds=60) is True


def test_touch_signal_creates_dir_and_file(tmp_path):
    path = str(tmp_path / "nested" / "logs" / "topup.signal")
    assert classify_topup.touch_signal(path) is True
    assert os.path.exists(path)


def test_signal_is_fresh_true_when_recent(tmp_path):
    path = str(tmp_path / "s.signal")
    classify_topup.touch_signal(path)
    assert classify_topup.signal_is_fresh(path, now=time.time(), max_age_seconds=600) is True


def test_signal_is_fresh_false_when_missing(tmp_path):
    path = str(tmp_path / "missing.signal")
    assert classify_topup.signal_is_fresh(path, now=time.time(), max_age_seconds=600) is False


def test_signal_is_fresh_false_when_stale(tmp_path):
    path = str(tmp_path / "s.signal")
    classify_topup.touch_signal(path)
    old = time.time() - 3600
    os.utime(path, (old, old))
    assert classify_topup.signal_is_fresh(path, now=time.time(), max_age_seconds=600) is False


def test_consume_signal_removes_file(tmp_path):
    path = str(tmp_path / "s.signal")
    classify_topup.touch_signal(path)
    assert classify_topup.consume_signal(path) is True
    assert not os.path.exists(path)


def test_consume_signal_missing_is_noop(tmp_path):
    path = str(tmp_path / "missing.signal")
    assert classify_topup.consume_signal(path) is False


# --- maybe_signal_topup (integration of the helpers) -----------------------

class _FakeQuery:
    def __init__(self, classified, pending):
        self._classified = classified
        self._pending = pending
        self.calls = 0

    def __call__(self, sql, one=False):
        self.calls += 1
        if "pending" in sql:
            return {"n": self._pending}
        return {"n": self._classified}


def test_maybe_signal_topup_triggers(tmp_path):
    path = str(tmp_path / "s.signal")
    q = _FakeQuery(classified=200, pending=50)
    verdict = classify_topup.maybe_signal_topup(
        q, page=1, page_size=40, signal_path=path, threshold=400)
    assert verdict == "triggered"
    assert os.path.exists(path)


def test_maybe_signal_topup_buffer_ok(tmp_path):
    path = str(tmp_path / "s.signal")
    q = _FakeQuery(classified=2000, pending=50)
    verdict = classify_topup.maybe_signal_topup(
        q, page=1, page_size=40, signal_path=path, threshold=400)
    assert verdict == "buffer_ok"
    assert not os.path.exists(path)


def test_maybe_signal_topup_no_pending_skips(tmp_path):
    path = str(tmp_path / "s.signal")
    q = _FakeQuery(classified=10, pending=0)
    verdict = classify_topup.maybe_signal_topup(
        q, page=1, page_size=40, signal_path=path, threshold=400)
    assert verdict == "no_pending"
    assert not os.path.exists(path)
    # Cheap: only the pending COUNT runs when it's zero.
    assert q.calls == 1


def test_maybe_signal_topup_cooldown_blocks(tmp_path):
    path = str(tmp_path / "s.signal")
    classify_topup.touch_signal(path)  # mtime = now
    mtime_before = os.path.getmtime(path)
    q = _FakeQuery(classified=200, pending=50)
    verdict = classify_topup.maybe_signal_topup(
        q, page=1, page_size=40, signal_path=path,
        threshold=400, cooldown_seconds=60, now=mtime_before + 5)
    assert verdict == "cooldown"
    # Cooldown blocked re-touch; mtime unchanged.
    assert os.path.getmtime(path) == mtime_before


def test_maybe_signal_topup_retouches_after_cooldown(tmp_path):
    path = str(tmp_path / "s.signal")
    classify_topup.touch_signal(path)
    old = time.time() - 3600
    os.utime(path, (old, old))
    q = _FakeQuery(classified=200, pending=50)
    verdict = classify_topup.maybe_signal_topup(
        q, page=1, page_size=40, signal_path=path,
        threshold=400, cooldown_seconds=60)
    assert verdict == "triggered"
    assert os.path.getmtime(path) > old


# --- classify_pending --triggered-only -------------------------------------

def test_triggered_only_exits_when_no_signal(tmp_path, monkeypatch):
    """No signal file = the cron tick is a fast no-op (it doesn't even
    take the lock). Verified by patching _run to assert it's never called."""
    import classify_pending
    sig = str(tmp_path / "absent.signal")
    monkeypatch.setattr(classify_pending, "_resolve_signal_path", lambda: sig)
    monkeypatch.setattr(classify_pending.Config, "CLASSIFY_TOPUP_SIGNAL_MAX_AGE", 600,
                        raising=False)
    monkeypatch.setattr(sys, "argv", ["classify_pending.py", "--triggered-only"])
    called = {"n": 0}
    def boom():
        called["n"] += 1
    monkeypatch.setattr(classify_pending, "_run", boom)
    classify_pending.main()
    assert called["n"] == 0


def test_triggered_only_exits_when_signal_stale(tmp_path, monkeypatch):
    import classify_pending
    sig = str(tmp_path / "old.signal")
    classify_topup.touch_signal(sig)
    old = time.time() - 7200
    os.utime(sig, (old, old))
    monkeypatch.setattr(classify_pending, "_resolve_signal_path", lambda: sig)
    monkeypatch.setattr(classify_pending.Config, "CLASSIFY_TOPUP_SIGNAL_MAX_AGE", 600,
                        raising=False)
    monkeypatch.setattr(sys, "argv", ["classify_pending.py", "--triggered-only"])
    called = {"n": 0}
    monkeypatch.setattr(classify_pending, "_run", lambda: called.__setitem__("n", called["n"] + 1))
    classify_pending.main()
    assert called["n"] == 0
    assert os.path.exists(sig)  # stale signal left alone


def test_triggered_only_runs_and_consumes_when_fresh(tmp_path, monkeypatch):
    import classify_pending
    sig = str(tmp_path / "fresh.signal")
    classify_topup.touch_signal(sig)
    monkeypatch.setattr(classify_pending, "_resolve_signal_path", lambda: sig)
    monkeypatch.setattr(classify_pending.Config, "CLASSIFY_TOPUP_SIGNAL_MAX_AGE", 600,
                        raising=False)
    monkeypatch.setattr(sys, "argv", ["classify_pending.py", "--triggered-only"])
    called = {"n": 0}
    monkeypatch.setattr(classify_pending, "_run", lambda: called.__setitem__("n", called["n"] + 1))
    classify_pending.main()
    assert called["n"] == 1
    assert not os.path.exists(sig)  # consumed inside the lock


def test_triggered_only_skips_run_when_lock_held(tmp_path, monkeypatch):
    """If another classify_pending is mid-run, the lock raises
    AlreadyRunning and we exit without running and without consuming
    the signal (it stays for the next 1-min tick)."""
    import classify_pending
    sig = str(tmp_path / "fresh.signal")
    classify_topup.touch_signal(sig)
    monkeypatch.setattr(classify_pending, "_resolve_signal_path", lambda: sig)
    monkeypatch.setattr(classify_pending.Config, "CLASSIFY_TOPUP_SIGNAL_MAX_AGE", 600,
                        raising=False)
    monkeypatch.setattr(sys, "argv", ["classify_pending.py", "--triggered-only"])

    from contextlib import contextmanager
    @contextmanager
    def fake_lock(name):
        raise classify_pending.AlreadyRunning(name)
        yield  # unreachable
    monkeypatch.setattr(classify_pending, "job_lock", fake_lock)

    called = {"n": 0}
    monkeypatch.setattr(classify_pending, "_run", lambda: called.__setitem__("n", called["n"] + 1))
    classify_pending.main()
    assert called["n"] == 0
    assert os.path.exists(sig)
