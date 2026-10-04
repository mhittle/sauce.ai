"""Per-host throttle: token bucket, shared 429 penalty, registry keying, config parsing."""
from app import throttle
from app.throttle import HostLimiter, Registry, parse_limits


class Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []
    def now(self):
        return self.t
    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def test_parse_limits():
    assert parse_limits("generativelanguage.googleapis.com=10, api.openai.com=500,bad,x=abc,y=0") == \
        {"generativelanguage.googleapis.com": 10.0, "api.openai.com": 500.0}
    assert parse_limits("") == {}


def test_bucket_spaces_requests_at_rpm():
    c = Clock()
    lim = HostLimiter(rpm=30, clock=c.now, sleep=c.sleep)     # one every 2 s
    assert lim.acquire() == 0.0
    assert lim.acquire() == 2.0 and lim.acquire() == 2.0
    assert c.slept == [2.0, 2.0] and lim.snapshot()["waits"] == 2


def test_unmetered_host_only_shares_penalties():
    c = Clock()
    lim = HostLimiter(rpm=None, clock=c.now, sleep=c.sleep)
    assert lim.acquire() == 0.0 and lim.acquire() == 0.0
    lim.penalize(7.0)
    assert lim.acquire() == 7.0                   # every caller waits out the 429
    assert lim.acquire() == 0.0                   # and is free again after it
    assert lim.snapshot()["penalties"] == 1


def test_registry_keys_by_host_and_applies_limits():
    reg = Registry({"generativelanguage.googleapis.com": 10})
    a = reg.for_url("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    b = reg.for_url("https://generativelanguage.googleapis.com/v1beta/openai")
    assert a is b and a.rpm == 10
    assert reg.for_url("https://api.openai.com/v1").rpm is None
    assert set(reg.snapshot()) == {"generativelanguage.googleapis.com", "api.openai.com"}


def test_process_registry_reads_settings(monkeypatch):
    from app.config import Settings
    throttle.reset_for_tests()
    reg = throttle.registry(Settings(db_path=":memory:", rpm_limits="example.test=5"))
    assert reg.for_url("https://example.test/x").rpm == 5
    throttle.reset_for_tests()
    assert throttle.registry(None).for_url("https://generativelanguage.googleapis.com/x").rpm is None   # unmetered by default
    throttle.reset_for_tests()


def test_target_429_penalizes_host_for_other_callers(monkeypatch):
    import app.targets as t
    from app.config import Settings
    from app.targets import TargetConfig, open_session
    throttle.reset_for_tests()
    settings = Settings(db_path=":memory:", rpm_limits="")
    waits = []
    monkeypatch.setattr(throttle.time, "sleep", waits.append)   # one time module: targets' sleep is patched too

    class R:
        def __init__(self, code, payload, headers=None):
            self.status_code, self._p, self.text, self.headers = code, payload, str(payload), headers or {}
        def json(self):
            return self._p
    replies = [R(429, {"e": "quota"}, {"Retry-After": "9"}), R(200, {"choices": [{"message": {"content": "ok"}}]})]
    monkeypatch.setattr(t.requests, "post", lambda *a, **k: replies.pop(0))
    sess = open_session(TargetConfig(kind="openai_chat", url="https://api.example.test/v1/chat/completions", model="m"), settings)
    assert sess.send("hi") == "ok"
    assert [round(w, 2) for w in waits] == [9.0]            # the retry waited out the shared penalty
    snap = throttle.registry(settings).for_url("https://api.example.test/v1").snapshot()
    assert snap["penalties"] == 1
    throttle.reset_for_tests()
