"""The brain: one frontier model, two modes.

A mode is a profile (system prompt + tool allowlist + optional model override),
not a separate agent. Both modes share the same vault tools and memory.

  build  — "Claude Code mode": agentic multi-step work, creating/editing notes,
           running workflows.
  code   — "Codex mode": code-execution-focused work (write code, run it, report).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import LLM
from .tools import Tool, call_tool

BASE_PROMPT = """You are Jarvis, a personal AI operating system for a content creator.
Your long-term memory is the user's Obsidian vault. Relevant notes are retrieved for you
below; cite them as [n] or by path when you rely on them. If the notes don't cover something,
say so instead of inventing past decisions.
Write durable facts, decisions, and deliverables back to the vault with the tools
(use `remember` for short facts; `vault_write` for documents). Never claim to have saved
something unless a tool call returned a saved path.
Today is {today}."""


@dataclass
class Mode:
    name: str
    instructions: str
    tools: list[str]


MODES: dict[str, Mode] = {
    "build": Mode(
        "build",
        "MODE: build. Plan briefly, then execute step by step with tools. Prefer producing a "
        "finished artifact saved in the vault over describing what you would do. Keep the final "
        "reply short: what you did, where it was saved, and anything the user must decide.",
        ["vault_search", "vault_read", "vault_write", "vault_append", "vault_list", "remember"],
    ),
    "code": Mode(
        "code",
        "MODE: code. You are a code-execution specialist. Write minimal, correct code, run it with "
        "run_python to verify before answering, and show the final code and its actual output. "
        "If execution is disabled, say so and give the code unverified, clearly labelled.",
        ["vault_search", "vault_read", "vault_write", "remember", "run_python"],
    ),
}


@dataclass
class BrainResult:
    reply: str
    steps: int
    tool_log: list[dict] = field(default_factory=list)
    saved: list[str] = field(default_factory=list)


class Brain:
    def __init__(self, llm: LLM, tools: dict[str, Tool], max_steps: int = 8):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps

    def system_prompt(self, mode: str, today: str, extra: str = "") -> str:
        m = MODES.get(mode, MODES["build"])
        parts = [BASE_PROMPT.format(today=today), m.instructions]
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    def run(self, *, mode: str, model: str, system: str, user: str,
            history: list[dict] | None = None, max_tokens: int = 4096) -> BrainResult:
        m = MODES.get(mode, MODES["build"])
        allowed = {n: self.tools[n] for n in m.tools if n in self.tools}
        schemas = [t.schema() for t in allowed.values()]
        messages = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": user}]
        log, saved = [], []
        for step in range(1, self.max_steps + 1):
            resp = self.llm.chat(messages, model=model, tools=schemas or None, max_tokens=max_tokens)
            if not resp.tool_calls:
                return BrainResult(resp.content.strip(), step, log, saved)
            messages.append({
                "role": "assistant", "content": resp.content or None,
                "tool_calls": [{"id": tc["id"] or f"call_{step}_{i}", "type": "function",
                                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                               for i, tc in enumerate(resp.tool_calls)],
            })
            for i, tc in enumerate(resp.tool_calls):
                if tc["name"] not in allowed:
                    result = f"error: tool {tc['name']} is not available in {mode} mode"
                else:
                    result = call_tool(allowed, tc["name"], tc["arguments"])
                log.append({"tool": tc["name"], "args": tc["arguments"], "result": result[:500]})
                if tc["name"] in {"vault_write", "vault_append", "remember"} and not result.startswith("error"):
                    try:
                        saved.append(next(iter(json.loads(result).values())))
                    except (json.JSONDecodeError, StopIteration):
                        pass
                messages.append({"role": "tool", "tool_call_id": tc["id"] or f"call_{step}_{i}",
                                 "content": result})
        # out of steps: ask for a final answer without tools
        messages.append({"role": "user", "content": "Step limit reached. Give your final answer now."})
        resp = self.llm.chat(messages, model=model, tools=None, max_tokens=max_tokens)
        return BrainResult(resp.content.strip(), self.max_steps + 1, log, saved)
