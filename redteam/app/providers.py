"""LLM provider layer for the attacker and judge ensembles.

A model is addressed by a spec string ``provider:model``:

    anthropic:claude-sonnet-5        Anthropic SDK
    openai:gpt-5                     OpenAI chat completions
    llama:meta-llama/Llama-3.3-70B-Instruct-Turbo   any OpenAI-compatible host
                                     (Together / Groq / Fireworks / vLLM / Ollama)
    gemini:gemini-2.5-pro            Gemini's OpenAI-compatible endpoint
    mock:<name>                      deterministic test double

Every model exposes ``chat(system, messages, max_tokens) -> str`` where
messages are ``[{"role": "user"|"assistant", "content": str}]``.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from .config import Settings


class ModelError(RuntimeError):
    pass


class ModelRefusal(ModelError):
    """The provider declined the request (safety classifier / refusal)."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    refusals: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, *, inp: int = 0, out: int = 0, refusal: bool = False, error: bool = False) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += inp
            self.output_tokens += out
            self.refusals += int(refusal)
            self.errors += int(error)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "refusals": self.refusals,
                "errors": self.errors}


class ChatModel:
    spec: str = ""

    def __init__(self) -> None:
        self.usage = Usage()

    def chat(self, system: str, messages: list[dict], max_tokens: int = 1024) -> str:
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

    def chat(self, system: str, messages: list[dict], max_tokens: int = 1024) -> str:
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
        inp = getattr(u, "input_tokens", 0) or 0
        out = getattr(u, "output_tokens", 0) or 0
        if resp.stop_reason == "refusal":
            self.usage.add(inp=inp, out=out, refusal=True)
            raise ModelRefusal(f"{self.spec} refused")
        self.usage.add(inp=inp, out=out)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


class OpenAICompatModel(ChatModel):
    """OpenAI chat-completions wire format (OpenAI, Llama hosts, Gemini)."""

    def __init__(self, provider: str, model: str, base_url: str, api_key: str | None,
                 timeout: float = 120.0) -> None:
        super().__init__()
        self.spec = f"{provider}:{model}"
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _body(self, system: str, messages: list[dict], max_tokens: int) -> dict:
        body: dict = {"model": self.model,
                      "messages": [{"role": "system", "content": system}, *messages]}
        # OpenAI's current models reject max_tokens in favour of max_completion_tokens.
        body["max_completion_tokens" if self.provider == "openai" else "max_tokens"] = max_tokens
        return body

    def chat(self, system: str, messages: list[dict], max_tokens: int = 1024) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = self._body(system, messages, max_tokens)
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.post(f"{self.base_url}/chat/completions", json=body,
                                  headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last = exc
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = ModelError(f"{self.spec}: HTTP {r.status_code}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                self.usage.add(error=True)
                raise ModelError(f"{self.spec}: HTTP {r.status_code} {r.text[:300]}")
            data = r.json()
            u = data.get("usage") or {}
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if msg.get("refusal") or choice.get("finish_reason") == "content_filter":
                self.usage.add(inp=u.get("prompt_tokens", 0), out=u.get("completion_tokens", 0), refusal=True)
                raise ModelRefusal(f"{self.spec} refused")
            self.usage.add(inp=u.get("prompt_tokens", 0) or 0, out=u.get("completion_tokens", 0) or 0)
            return (msg.get("content") or "").strip()
        self.usage.add(error=True)
        raise ModelError(f"{self.spec}: retries exhausted ({last})")


Responder = Callable[[str, list[dict]], str]


class MockModel(ChatModel):
    """Test double. ``responder(system, messages)`` supplies the reply."""

    def __init__(self, name: str, responder: Responder | None = None) -> None:
        super().__init__()
        self.spec = f"mock:{name}"
        self.responder = responder or (lambda s, m: "ok")

    def chat(self, system: str, messages: list[dict], max_tokens: int = 1024) -> str:
        self.usage.add()
        return self.responder(system, messages)


PROVIDERS = ("anthropic", "openai", "llama", "gemini", "mock")

# Curated, human-picked model lists for the UI dropdowns. Not exhaustive and
# not validated against a live models API — the researcher can always type a
# custom `provider:model`, and an unknown id simply 404s at call time. Keep
# ordered best-first within a provider; labels are what the dropdown shows.
MODEL_CATALOG: dict[str, list[dict]] = {
    "anthropic": [
        {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
        {"id": "claude-opus-5", "label": "Claude Opus 5"},
        {"id": "claude-sonnet-5", "label": "Claude Sonnet 5"},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
        {"id": "claude-fable-5-1", "label": "Claude Fable 5.1"},
    ],
    "openai": [
        {"id": "gpt-5", "label": "GPT-5"},
        {"id": "gpt-4o", "label": "GPT-4o"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
        {"id": "o4-mini", "label": "o4-mini"},
    ],
    "llama": [
        {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "label": "Llama 3.3 70B Instruct (Together)"},
        {"id": "meta-llama/Llama-3.1-8B-Instruct-Turbo", "label": "Llama 3.1 8B Instruct (Together)"},
        {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "label": "Llama 3.1 70B Instruct (Together)"},
    ],
    "gemini": [
        {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    ],
}


def model_catalog(settings: Settings) -> list[dict]:
    """Flat catalog for the UI: one row per known model, tagged with whether
    its provider has a key configured on the server (unconfigured models are
    shown but disabled)."""
    avail = set(available_providers(settings))
    return [
        {"spec": f"{prov}:{m['id']}", "provider": prov, "model": m["id"],
         "label": m["label"], "available": prov in avail}
        for prov, models in MODEL_CATALOG.items() for m in models
    ]


def parse_spec(spec: str) -> tuple[str, str]:
    provider, sep, model = (spec or "").strip().partition(":")
    if not sep or provider not in PROVIDERS or not model:
        raise ValueError(f"bad model spec {spec!r}; expected one of {PROVIDERS} as 'provider:model'")
    return provider, model


def available_providers(settings: Settings) -> list[str]:
    out = []
    if settings.anthropic_api_key:
        out.append("anthropic")
    if settings.openai_api_key:
        out.append("openai")
    if settings.llama_api_key or "localhost" in settings.llama_base_url:
        out.append("llama")
    if settings.gemini_api_key:
        out.append("gemini")
    return out


def build_model(spec: str, settings: Settings,
                mocks: dict[str, ChatModel] | None = None) -> ChatModel:
    provider, model = parse_spec(spec)
    if provider == "mock":
        if mocks and spec in mocks:
            return mocks[spec]
        return MockModel(model)
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ModelError("ANTHROPIC_API_KEY is not configured")
        return AnthropicModel(model, settings.anthropic_api_key, settings.anthropic_refusal_fallback)
    if provider == "openai":
        if not settings.openai_api_key:
            raise ModelError("OPENAI_API_KEY is not configured")
        return OpenAICompatModel("openai", model, settings.openai_base_url, settings.openai_api_key)
    if provider == "llama":
        return OpenAICompatModel("llama", model, settings.llama_base_url, settings.llama_api_key)
    if not settings.gemini_api_key:
        raise ModelError("GEMINI_API_KEY is not configured")
    return OpenAICompatModel("gemini", model, settings.gemini_base_url, settings.gemini_api_key)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str):
    """Tolerant JSON extraction: fenced block, then the outermost {...} / [...]."""
    if not text:
        raise ValueError("empty model output")
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for c in candidates:
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


def chat_json(model: ChatModel, system: str, messages: list[dict], max_tokens: int = 1500):
    """One call + one repair retry when the output is not parseable JSON."""
    text = model.chat(system, messages, max_tokens)
    try:
        return parse_json(text)
    except ValueError:
        repair = [*messages, {"role": "assistant", "content": text or "(empty)"},
                  {"role": "user", "content": "Your reply was not valid JSON. Reply again with only the JSON object."}]
        return parse_json(model.chat(system, repair, max_tokens))
