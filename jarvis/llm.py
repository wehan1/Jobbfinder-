"""Model clients. One OpenAI-compatible client covers OpenRouter, OpenAI, local
llama.cpp/Ollama servers, etc. `FakeLLM` is a scripted stand-in for tests and
offline demos."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{"id","name","arguments": dict}]
    model: str = ""
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    def chat(self, messages: list[dict], model: str, tools: list[dict] | None = None,
             max_tokens: int = 2048, temperature: float = 0.3) -> LLMResponse: ...


class LLMError(RuntimeError):
    pass


class OpenAICompatLLM:
    def __init__(self, base_url: str, api_key: str, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        # Some proxies inject the key themselves; send a placeholder so the header exists.
        self.api_key = api_key or "sk-placeholder"
        self.timeout = timeout

    def chat(self, messages, model, tools=None, max_tokens=2048, temperature=0.3) -> LLMResponse:
        payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens,
                         "temperature": temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": os.environ.get("JARVIS_APP_URL", "http://localhost"),
                "X-Title": "Jarvis",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise LLMError(f"{e.code} from model API: {e.read().decode(errors='replace')[:500]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"model API unreachable: {e.reason}") from e
        if "error" in data:
            raise LLMError(str(data["error"])[:500])
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments")}
            calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": args})
        return LLMResponse(content=msg.get("content") or "", tool_calls=calls,
                           model=data.get("model", model), usage=data.get("usage", {}))


class FakeLLM:
    """Deterministic LLM for tests. `responder(messages, model, tools)` returns a
    str or an LLMResponse. Every call is recorded in `.calls`."""

    def __init__(self, responder: Callable | None = None):
        self.responder = responder or (lambda m, model, tools: f"[{model}] ok")
        self.calls: list[dict] = []

    def chat(self, messages, model, tools=None, max_tokens=2048, temperature=0.3) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model, "tools": tools})
        out = self.responder(messages, model, tools)
        if isinstance(out, LLMResponse):
            out.model = out.model or model
            return out
        return LLMResponse(content=str(out), model=model)
