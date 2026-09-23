"""Model layer. A model is addressed as ``provider:model``:

    anthropic:claude-opus-5     Anthropic SDK
    mock:<name>                 deterministic test double

Every model exposes ``chat(system, messages, max_tokens) -> str``.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from .config import Settings


class ModelError(RuntimeError):
    pass


class ModelRefusal(ModelError):
    """The provider declined the request."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, *, inp: int = 0, out: int = 0, error: bool = False) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += inp
            self.output_tokens += out
            self.errors += int(error)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "errors": self.errors}


class ChatModel:
    spec: str = ""

    def __init__(self) -> None:
        self.usage = Usage()

    def chat(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        raise NotImplementedError


# Models that support Anthropic's server-side refusal fallback.
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5")


class AnthropicModel(ChatModel):
    def __init__(self, model: str, api_key: str, refusal_fallback: bool = True) -> None:
        super().__init__()
        import anthropic
        self.spec = f"anthropic:{model}"
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.refusal_fallback = refusal_fallback and model.startswith(_FALLBACK_MODELS)

    def chat(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        import anthropic
        kwargs: dict = {}
        if self.refusal_fallback:
            kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
            kwargs["extra_body"] = {"fallbacks": "default"}
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=messages, **kwargs)
        except anthropic.APIError as exc:
            self.usage.add(error=True)
            raise ModelError(f"{self.spec}: {exc}") from exc
        u = getattr(resp, "usage", None)
        self.usage.add(inp=getattr(u, "input_tokens", 0) or 0, out=getattr(u, "output_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            raise ModelRefusal(f"{self.spec} refused")
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


Responder = Callable[[str, list[dict]], str]


class MockModel(ChatModel):
    """Test double. ``responder(system, messages)`` supplies the reply."""

    def __init__(self, name: str, responder: Responder | None = None) -> None:
        super().__init__()
        self.spec = f"mock:{name}"
        self.responder = responder or (lambda s, m: "{}")

    def chat(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        self.usage.add()
        return self.responder(system, messages)


PROVIDERS = ("anthropic", "mock")


def parse_spec(spec: str) -> tuple[str, str]:
    provider, sep, model = (spec or "").strip().partition(":")
    if not sep or provider not in PROVIDERS or not model:
        raise ValueError(f"bad model spec {spec!r}; expected 'anthropic:<model>'")
    return provider, model


def build_model(spec: str, settings: Settings, mocks: dict[str, ChatModel] | None = None) -> ChatModel:
    provider, model = parse_spec(spec)
    if provider == "mock":
        return (mocks or {}).get(spec) or MockModel(model)
    if not settings.anthropic_api_key:
        raise ModelError("ANTHROPIC_API_KEY is not configured")
    return AnthropicModel(model, settings.anthropic_api_key, settings.anthropic_refusal_fallback)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str):
    """Tolerant JSON extraction: fenced block, then the outermost {...} / [...]."""
    if not text:
        raise ValueError("empty model output")
    for c in [m.group(1) for m in _FENCE.finditer(text)] + [text]:
        c = c.strip()
        try:
            return json.loads(c)
        except ValueError:
            pass
        for open_, close in (("{", "}"), ("[", "]")):
            i, j = c.find(open_), c.rfind(close)
            if 0 <= i < j:
                try:
                    return json.loads(c[i:j + 1])
                except ValueError:
                    continue
    raise ValueError("no JSON object in model output")


def chat_json(model: ChatModel, system: str, messages: list[dict], max_tokens: int = 4096):
    """One call + one repair retry when the output is not parseable JSON."""
    text = model.chat(system, messages, max_tokens)
    try:
        return parse_json(text)
    except ValueError:
        repair = [*messages, {"role": "assistant", "content": text or "(empty)"},
                  {"role": "user", "content": "Your reply was not valid JSON. Reply again with only the JSON object."}]
        return parse_json(model.chat(system, repair, max_tokens))
