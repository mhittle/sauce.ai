"""Target adapters, SSRF guard, provider spec parsing/JSON."""
import pytest

from app import netguard
from app.providers import ModelError, parse_spec, parse_json, MockModel, build_model
from app.config import Settings
from app.targets import (TargetConfig, TargetError, dig, render_template,
                         validate_config, open_session)


def test_model_catalog_marks_availability():
    from app.providers import model_catalog
    cat = model_catalog(Settings(anthropic_api_key="k", openai_api_key=None,
                                 llama_api_key=None, gemini_api_key=None))
    specs = {m["spec"]: m for m in cat}
    assert specs["anthropic:claude-sonnet-5"]["available"] is True
    assert specs["openai:gpt-5"]["available"] is False
    # every row is a valid provider:model spec
    for m in cat:
        parse_spec(m["spec"])
    assert all(k in m for m in cat for k in ("spec", "provider", "model", "label", "available"))


def test_parse_spec_valid_and_invalid():
    assert parse_spec("anthropic:claude-opus-5") == ("anthropic", "claude-opus-5")
    for bad in ("", "noprovider", "unknown:model", "openai:"):
        with pytest.raises(ValueError):
            parse_spec(bad)


def test_parse_json_from_fence_and_noise():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('sure, here: {"b": [1,2]} done') == {"b": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_dig_resolves_paths():
    data = {"choices": [{"message": {"content": "hi"}}]}
    assert dig(data, "choices.0.message.content") == "hi"
    with pytest.raises(TargetError):
        dig(data, "choices.5.message")


def test_render_template_escapes_and_expands():
    body = render_template('{"m": "{{message}}", "hist": {{messages_json}}}',
                           message='say "hi"', history=[{"role": "user", "content": "x"}],
                           conversation_id="c", system_prompt="")
    assert body["m"] == 'say "hi"'
    assert body["hist"] == [{"role": "user", "content": "x"}]


def test_ssrf_blocks_private_and_metadata():
    for host in ("http://127.0.0.1/x", "http://169.254.169.254/latest",
                 "http://10.0.0.5/", "ftp://example.com/"):
        with pytest.raises(netguard.UnsafeTarget):
            netguard.check_url(host, allow_private=False,
                               resolver=lambda h, p: [(2, 1, 6, "", ("10.0.0.1", p))])


def test_ssrf_allows_public():
    url = "https://api.example.com/v1/chat"
    out = netguard.check_url(url, allow_private=False,
                             resolver=lambda h, p: [(2, 1, 6, "", ("93.184.216.34", p))])
    assert out == url


def test_ssrf_allow_private_flag_bypasses():
    assert netguard.check_url("http://127.0.0.1/x", allow_private=True) == "http://127.0.0.1/x"


def test_validate_config_requirements():
    # a blank URL on the OpenAI-compatible kind means OpenAI itself
    cfg = TargetConfig(kind="openai_chat")
    assert cfg.url == "https://api.openai.com/v1/chat/completions"
    validate_config(cfg)
    assert TargetConfig(kind="openai_chat", url=" https://api.groq.com/openai/v1/chat/completions ").url.startswith("https://api.groq")
    assert TargetConfig(kind="anthropic").url == ""  # SDK default base URL
    with pytest.raises(ValueError):
        validate_config(TargetConfig(kind="http_json"))  # no url, no default
    with pytest.raises(ValueError):
        validate_config(TargetConfig(kind="anthropic"))  # no model/key
    with pytest.raises(ValueError):
        validate_config(TargetConfig(kind="http_json", url="https://x", body_template="{}"))  # no response_path
    validate_config(TargetConfig(kind="openai_chat", url="https://api.example.com"))


def test_public_dict_hides_secrets():
    cfg = TargetConfig(kind="openai_chat", url="https://x", api_key="secret", headers={"X-Key": "s"})
    pub = cfg.public_dict()
    assert "secret" not in str(pub) and pub["has_api_key"] is True


def test_build_model_mock_and_missing_key():
    s = Settings(anthropic_api_key=None)
    assert isinstance(build_model("mock:x", s, {}), MockModel)
    with pytest.raises(ModelError):
        build_model("anthropic:claude-opus-5", s)


class _FakeResp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._p = payload
        self.text = str(payload)
        self.headers = headers or {}

    def json(self):
        return self._p


def test_openai_chat_session_roundtrip(monkeypatch):
    import app.targets as t

    def fake_post(url, json, headers, timeout, allow_redirects):
        assert json["messages"][-1]["content"] == "hello"
        return _FakeResp(200, {"choices": [{"message": {"content": "hi there"}}]})

    monkeypatch.setattr(t.requests, "post", fake_post)
    sess = open_session(TargetConfig(kind="openai_chat", url="https://api.example.com", model="m"), Settings())
    assert sess.send("hello") == "hi there"
    assert sess.history[-1] == {"role": "assistant", "content": "hi there"}


def test_http_json_error_status_raises(monkeypatch):
    import app.targets as t
    monkeypatch.setattr(t.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(t.requests, "post",
                        lambda *a, **k: (calls.append(1), _FakeResp(500, {"error": "boom"}))[1])
    sess = open_session(TargetConfig(kind="openai_chat", url="https://api.example.com"), Settings())
    with pytest.raises(TargetError, match="after 6 attempts"):
        sess.send("x")
    assert len(calls) == t.TargetSession.RETRY_ATTEMPTS
    assert sess.history == []  # failed user turn rolled back


def test_target_retries_rate_limit_then_succeeds(monkeypatch):
    import app.targets as t
    slept = []
    monkeypatch.setattr(t.time, "sleep", slept.append)
    replies = [_FakeResp(429, {"error": "quota"}, {"Retry-After": "3"}), _FakeResp(503, {"error": "busy"}),
               _FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})]
    monkeypatch.setattr(t.requests, "post", lambda *a, **k: replies.pop(0))
    sess = open_session(TargetConfig(kind="openai_chat", url="https://api.example.com", model="m"), Settings())
    assert sess.send("hello") == "ok"
    assert slept == [3.0, 4.0]          # Retry-After honoured, then 2^(attempt+1)
    assert t._retry_delay("garbage", 5, 45.0) == 45.0 and t._retry_delay("900", 0, 45.0) == 2.0


def test_target_4xx_other_than_429_fails_fast(monkeypatch):
    import app.targets as t
    calls = []
    monkeypatch.setattr(t.requests, "post", lambda *a, **k: (calls.append(1), _FakeResp(404, {"error": "no model"}))[1])
    sess = open_session(TargetConfig(kind="openai_chat", url="https://api.example.com"), Settings())
    with pytest.raises(TargetError, match="HTTP 404"):
        sess.send("x")
    assert len(calls) == 1


def test_gemini_base_normalization_and_openrouter_fallback():
    from app.providers import gemini_openai_base, llama_host, available_providers, build_model, OpenAICompatModel
    assert gemini_openai_base("https://generativelanguage.googleapis.com/v1beta/models/") == \
        "https://generativelanguage.googleapis.com/v1beta/openai"
    assert gemini_openai_base("https://generativelanguage.googleapis.com/v1beta") == \
        "https://generativelanguage.googleapis.com/v1beta/openai"
    assert gemini_openai_base("https://generativelanguage.googleapis.com/v1beta/openai/") == \
        "https://generativelanguage.googleapis.com/v1beta/openai"
    assert gemini_openai_base("https://proxy.example/v1") == "https://proxy.example/v1"
    assert gemini_openai_base("") == "https://generativelanguage.googleapis.com/v1beta/openai"
    s = Settings(llama_api_key=None, openrouter_api_key="ork", llama_base_url="https://api.together.xyz/v1",
                 gemini_api_key="gk", gemini_base_url="https://generativelanguage.googleapis.com/v1beta/models/")
    assert llama_host(s) == ("https://openrouter.ai/api/v1", "ork", "openrouter")
    assert "llama" in available_providers(s)
    m = build_model("llama:meta-llama/llama-3.3-70b-instruct", s)
    assert isinstance(m, OpenAICompatModel) and m.base_url == "https://openrouter.ai/api/v1" and m.api_key == "ork"
    g = build_model("gemini:gemini-2.5-flash", s)
    assert g.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    # an explicit LLAMA key wins over OpenRouter
    s2 = Settings(llama_api_key="lk", openrouter_api_key="ork", llama_base_url="https://api.groq.com/openai/v1")
    assert llama_host(s2) == ("https://api.groq.com/openai/v1", "lk", "llama")
