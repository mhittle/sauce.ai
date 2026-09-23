"""Scripted stand-in for the Anthropic client (no network)."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS


def text(t):
    return NS(type="text", text=t)


def tool_use(name, input_, id_="tu_1"):
    return NS(type="tool_use", name=name, input=input_, id=id_)


def response(content, stop_reason, in_tok=100, out_tok=50):
    return NS(content=content, stop_reason=stop_reason,
              usage=NS(input_tokens=in_tok, output_tokens=out_tok))


class FakeClient:
    """Plans with ``plan`` for structured-output calls; otherwise pops worker
    responses from ``script`` (then ends the turn)."""

    def __init__(self, plan: dict, script: list | None = None):
        self.plan = plan
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        # Snapshot: the agent keeps appending to the same messages list.
        self.calls.append({**kw, "messages": list(kw.get("messages", []))})
        if "format" in (kw.get("output_config") or {}):
            return response([text(json.dumps(self.plan))], "end_turn")
        if self.script:
            return self.script.pop(0)
        return response([text("done")], "end_turn")
