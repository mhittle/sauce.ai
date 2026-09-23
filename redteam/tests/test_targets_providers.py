"""Target adapters, SSRF guard, provider spec parsing/JSON."""
import pytest

from app import netguard
from app.providers import ModelError, parse_spec, parse_json, MockModel, build_model
from app.config import Settings
from app.targets import (TargetConfig, TargetError, dig, render_template,
                         validate_config, open_session)


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
    with pytest.raises(ValueError):
        validate_config(TargetConfig(kind="openai_chat"))  # no url
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
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = str(payload)

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
    monkeypatch.setattr(t.requests, "post",
                        lambda *a, **k: _FakeResp(500, {"error": "boom"}))
    sess = open_session(TargetConfig(kind="openai_chat", url="https://api.example.com"), Settings())
    with pytest.raises(TargetError):
        sess.send("x")
    assert sess.history == []  # failed user turn rolled back
