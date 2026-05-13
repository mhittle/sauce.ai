"""Unit tests for the dossier framing-summary helper.

`anthropic` is stubbed via `sys.modules` so these tests run without the
SDK installed (the production helper imports lazily and we mirror that).
"""
import json
import sys
import types

import pytest

from app.classifier import LLMUnavailable
from app.classifier import framing as framing_mod


def _install_fake_anthropic(monkeypatch, *, response_text=None, raise_on_create=None):
    """Inject a fake `anthropic` module into sys.modules for this test."""
    class _Block:
        def __init__(self, t, text):
            self.type = t
            self.text = text

    class _Usage:
        input_tokens = 100
        output_tokens = 50
        cache_read_input_tokens = 0

    class _Resp:
        def __init__(self, text):
            self.content = [_Block("text", text)]
            self.usage = _Usage()

    captured = {"system": None, "messages": None, "model": None}

    class _Messages:
        def create(self, *, model, max_tokens, system, messages, timeout):
            if raise_on_create is not None:
                raise raise_on_create
            captured["model"] = model
            captured["system"] = system
            captured["messages"] = messages
            return _Resp(response_text)

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    stub = types.ModuleType("anthropic")
    stub.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", stub)
    return captured


def test_generate_framing_happy_path(monkeypatch):
    captured = _install_fake_anthropic(
        monkeypatch,
        response_text=json.dumps({"summary": "Left and right diverged on framing."}),
    )
    members = [
        {"source_name": "L", "source_lean": -0.5, "political_lean": -0.4,
         "title": "Headline A", "lead": "Lead from A."},
        {"source_name": "R", "source_lean": 0.5, "political_lean": 0.4,
         "title": "Headline B", "lead": "Lead from B."},
    ]
    out = framing_mod.generate_framing(members, api_key="k", model="m")
    assert out["summary"] == "Left and right diverged on framing."
    assert out["usage"]["model"] == "m"
    user_text = captured["messages"][0]["content"]
    assert "Headline A" in user_text and "Headline B" in user_text
    assert "outlet_lean=-0.50" in user_text and "outlet_lean=+0.50" in user_text


def test_generate_framing_strips_code_fences(monkeypatch):
    _install_fake_anthropic(
        monkeypatch,
        response_text='```json\n{"summary": "wrapped"}\n```',
    )
    out = framing_mod.generate_framing(
        [{"source_name": "X", "source_lean": 0, "political_lean": 0, "title": "T", "lead": "L"}],
        api_key="k", model="m",
    )
    assert out["summary"] == "wrapped"


def test_no_api_key_raises():
    with pytest.raises(LLMUnavailable):
        framing_mod.generate_framing(
            [{"source_name": "X", "source_lean": 0, "political_lean": 0, "title": "T", "lead": "L"}],
            api_key="", model="m",
        )


def test_empty_members_raises():
    with pytest.raises(LLMUnavailable):
        framing_mod.generate_framing([], api_key="k", model="m")


def test_api_exception_wrapped(monkeypatch):
    _install_fake_anthropic(monkeypatch, raise_on_create=RuntimeError("boom"))
    with pytest.raises(LLMUnavailable):
        framing_mod.generate_framing(
            [{"source_name": "X", "source_lean": 0, "political_lean": 0, "title": "T", "lead": "L"}],
            api_key="k", model="m",
        )


def test_unparseable_response_raises(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text="not json at all")
    with pytest.raises(LLMUnavailable):
        framing_mod.generate_framing(
            [{"source_name": "X", "source_lean": 0, "political_lean": 0, "title": "T", "lead": "L"}],
            api_key="k", model="m",
        )


def test_empty_summary_raises(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=json.dumps({"summary": "   "}))
    with pytest.raises(LLMUnavailable):
        framing_mod.generate_framing(
            [{"source_name": "X", "source_lean": 0, "political_lean": 0, "title": "T", "lead": "L"}],
            api_key="k", model="m",
        )


def test_caps_member_count(monkeypatch):
    captured = _install_fake_anthropic(
        monkeypatch,
        response_text=json.dumps({"summary": "ok"}),
    )
    members = [
        {"source_name": f"S{i}", "source_lean": 0.0, "political_lean": 0.0,
         "title": f"T{i}", "lead": "L"}
        for i in range(20)
    ]
    framing_mod.generate_framing(members, api_key="k", model="m", max_members=5)
    user_text = captured["messages"][0]["content"]
    assert "S0" in user_text and "S4" in user_text
    assert "S5" not in user_text
    assert "Cluster of 5 articles" in user_text


def test_render_members_block_truncates_long_leads():
    m = [{"source_name": "X", "source_lean": 0.0, "political_lean": 0.0,
          "title": "T", "lead": "x" * 1000}]
    out = framing_mod._render_members_block(m)
    # 400-char cap on lead
    assert out.count("x") <= 400
