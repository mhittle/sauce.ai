"""Adapters for the system under test (the clinical chatbot being red-teamed).

Kinds:

- ``openai_chat``  OpenAI-compatible ``/chat/completions`` URL (most LLM APIs,
  Azure OpenAI, vLLM, Ollama, Llama hosts, Gemini's compat endpoint).
- ``anthropic``    Anthropic Messages API (optionally a custom base URL).
- ``http_json``    Any JSON endpoint: a body template with placeholders and
  a dotted response path. Stateless (full history each call) or stateful
  (latest message + conversation id).
- ``web_chat``     A chat web page driven by Playwright via CSS selectors.

Target credentials live only in memory for the life of a run.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import requests

from .config import Settings
from .providers import AnthropicModel, ModelError

TARGET_KINDS = ("openai_chat", "anthropic", "http_json", "web_chat")


class TargetError(RuntimeError):
    pass


@dataclass
class TargetConfig:
    kind: str
    url: str = ""
    model: str = ""
    api_key: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    system_prompt: str = ""
    headers: dict = field(default_factory=dict)
    body_template: str = ""
    response_path: str = ""
    stateful: bool = False
    input_selector: str = ""
    send_selector: str = ""
    response_selector: str = ""
    timeout: float = 90.0

    def public_dict(self) -> dict:
        """Everything but secrets, for persistence and the report."""
        d = {k: v for k, v in self.__dict__.items() if k not in ("api_key", "headers")}
        d["headers"] = sorted(self.headers)
        d["has_api_key"] = bool(self.api_key)
        return d


def dig(data, path: str):
    """Resolve a dotted path (``choices.0.message.content``) into JSON."""
    cur = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise TargetError(f"response path {path!r} failed at {part!r}") from exc
        elif isinstance(cur, dict):
            if part not in cur:
                raise TargetError(f"response path {path!r} failed at {part!r}")
            cur = cur[part]
        else:
            raise TargetError(f"response path {path!r} failed at {part!r}")
    if isinstance(cur, (dict, list)):
        return json.dumps(cur)
    return "" if cur is None else str(cur)


def render_template(template: str, *, message: str, history: list[dict], conversation_id: str,
                    system_prompt: str) -> dict:
    """Fill a JSON body template. Placeholders are replaced inside JSON string
    literals with properly escaped values; ``{{messages_json}}`` must appear
    bare (unquoted) because it expands to an array."""
    def esc(s: str) -> str:
        return json.dumps(s)[1:-1]

    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    out = (template
           .replace("{{messages_json}}", json.dumps(history))
           .replace("{{message}}", esc(message))
           .replace("{{history_text}}", esc(transcript))
           .replace("{{conversation_id}}", esc(conversation_id))
           .replace("{{system_prompt}}", esc(system_prompt)))
    try:
        return json.loads(out)
    except ValueError as exc:
        raise TargetError(f"body template is not valid JSON after substitution: {exc}") from exc


class TargetSession:
    """One synthetic conversation with the target."""

    def __init__(self, cfg: TargetConfig, settings: Settings) -> None:
        self.cfg = cfg
        self.settings = settings
        self.history: list[dict] = []
        self.conversation_id = uuid.uuid4().hex

    def send(self, message: str) -> str:
        self.history.append({"role": "user", "content": message})
        try:
            reply = self._send(message)
        except TargetError:
            self.history.pop()
            raise
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def _send(self, message: str) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def _auth_headers(self) -> dict:
        h = {"Content-Type": "application/json", **self.cfg.headers}
        if self.cfg.api_key:
            h[self.cfg.auth_header] = f"{self.cfg.auth_prefix}{self.cfg.api_key}"
        return h

    def _post(self, body: dict) -> dict:
        try:
            r = requests.post(self.cfg.url, json=body, headers=self._auth_headers(),
                              timeout=self.cfg.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise TargetError(f"target unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise TargetError(f"target HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as exc:
            raise TargetError("target did not return JSON") from exc


class OpenAIChatSession(TargetSession):
    def _send(self, message: str) -> str:
        msgs = ([{"role": "system", "content": self.cfg.system_prompt}] if self.cfg.system_prompt else []) + self.history
        body: dict = {"messages": msgs}
        if self.cfg.model:
            body["model"] = self.cfg.model
        return dig(self._post(body), self.cfg.response_path or "choices.0.message.content")


class AnthropicSession(TargetSession):
    def __init__(self, cfg: TargetConfig, settings: Settings) -> None:
        super().__init__(cfg, settings)
        self.model = AnthropicModel(cfg.model, cfg.api_key, refusal_fallback=False)
        if cfg.url:
            import anthropic
            self.model.client = anthropic.Anthropic(api_key=cfg.api_key, base_url=cfg.url, max_retries=3)

    def _send(self, message: str) -> str:
        try:
            return self.model.chat(self.cfg.system_prompt or "You are a helpful assistant.",
                                   list(self.history), max_tokens=2048)
        except ModelError as exc:
            # A refusal is a (safe) target response, not an error.
            if "refused" in str(exc):
                return "[target declined to respond]"
            raise TargetError(str(exc)) from exc


class HttpJsonSession(TargetSession):
    def _send(self, message: str) -> str:
        history = self.history[-1:] if self.cfg.stateful else self.history
        body = render_template(self.cfg.body_template, message=message, history=history,
                               conversation_id=self.conversation_id,
                               system_prompt=self.cfg.system_prompt)
        return dig(self._post(body), self.cfg.response_path)


class WebChatSession(TargetSession):
    """Playwright-driven chat page. Optional dependency; imported lazily."""

    def __init__(self, cfg: TargetConfig, settings: Settings) -> None:
        super().__init__(cfg, settings)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TargetError("web_chat targets need `pip install playwright`") from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page()
        self._page.goto(cfg.url, timeout=cfg.timeout * 1000)

    def _send(self, message: str) -> str:
        page, cfg = self._page, self.cfg
        before = page.locator(cfg.response_selector).count()
        page.fill(cfg.input_selector, message)
        if cfg.send_selector:
            page.click(cfg.send_selector)
        else:
            page.press(cfg.input_selector, "Enter")
        deadline = time.time() + cfg.timeout
        last, stable = "", 0
        while time.time() < deadline:
            loc = page.locator(cfg.response_selector)
            if loc.count() > before:
                text = loc.nth(loc.count() - 1).inner_text()
                stable = stable + 1 if text == last and text else 0
                last = text
                if stable >= 3:  # streamed replies: wait for the text to settle
                    return text.strip()
            time.sleep(0.5)
        if last:
            return last.strip()
        raise TargetError("web chat produced no reply before timeout")

    def close(self) -> None:
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass


_SESSIONS = {"openai_chat": OpenAIChatSession, "anthropic": AnthropicSession,
             "http_json": HttpJsonSession, "web_chat": WebChatSession}


def validate_config(cfg: TargetConfig) -> None:
    if cfg.kind not in TARGET_KINDS:
        raise ValueError(f"unknown target kind {cfg.kind!r}")
    if cfg.kind != "anthropic" and not cfg.url:
        raise ValueError("target URL is required")
    if cfg.kind == "anthropic" and not (cfg.model and cfg.api_key):
        raise ValueError("anthropic targets need a model and API key")
    if cfg.kind == "http_json":
        if not cfg.body_template or not cfg.response_path:
            raise ValueError("http_json targets need a body template and response path")
        render_template(cfg.body_template, message="x", history=[{"role": "user", "content": "x"}],
                        conversation_id="c", system_prompt="")
    if cfg.kind == "web_chat" and not (cfg.input_selector and cfg.response_selector):
        raise ValueError("web_chat targets need input and response CSS selectors")


def open_session(cfg: TargetConfig, settings: Settings) -> TargetSession:
    return _SESSIONS[cfg.kind](cfg, settings)
