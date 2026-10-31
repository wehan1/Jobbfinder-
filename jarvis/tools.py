"""Tools the brain can call. Every tool is scoped to the vault."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from .rag import Retriever
from .vault import Vault, VaultError


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., str]

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


def build_tools(vault: Vault, retriever: Retriever, allow_code_exec: bool) -> dict[str, Tool]:
    def vault_search(query: str, k: int = 6) -> str:
        hits = retriever.search(query, k=int(k))
        return json.dumps([{**h.as_dict(), "text": h.text[:800]} for h in hits], ensure_ascii=False)

    def vault_read(path: str) -> str:
        rel = vault.find_note(path) or path
        text = vault.read(rel)
        return text[:20000] + ("\n…(truncated)" if len(text) > 20000 else "")

    def vault_write(path: str, content: str, overwrite: bool = False) -> str:
        rel = vault.write(path, content, overwrite=bool(overwrite))
        return json.dumps({"saved": rel})

    def vault_append(path: str, text: str) -> str:
        return json.dumps({"appended": vault.append(path, text)})

    def vault_list(prefix: str = "") -> str:
        notes = [n for n in vault.list_notes() if n.startswith(prefix)]
        return json.dumps(notes[:300])

    def remember(fact: str) -> str:
        return json.dumps({"saved": vault.remember(fact, source="brain")})

    def run_python(code: str) -> str:
        if not allow_code_exec:
            return "error: code execution is disabled (set JARVIS_ALLOW_CODE_EXEC=1 to enable)"
        sandbox = vault.state_dir / "sandbox"
        sandbox.mkdir(parents=True, exist_ok=True)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sandbox), "PYTHONIOENCODING": "utf-8"}
        try:
            proc = subprocess.run([sys.executable, "-I", "-c", code], cwd=sandbox, env=env,
                                  capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return "error: timed out after 30s"
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return f"exit={proc.returncode}\n{out[:8000]}"

    s = lambda **props: {"type": "object", "properties": props,  # noqa: E731
                         "required": [k for k, v in props.items() if not v.pop("optional", False)]}
    tools = [
        Tool("vault_search", "Search the user's Obsidian vault (BM25). Returns matching chunks with paths and dates.",
             s(query={"type": "string"}, k={"type": "integer", "optional": True}), vault_search),
        Tool("vault_read", "Read a full note by vault-relative path or note name.",
             s(path={"type": "string"}), vault_read),
        Tool("vault_write", "Create a markdown note in the vault. Paths are vault-relative, e.g. 'Jarvis/Inbox/idea.md'.",
             s(path={"type": "string"}, content={"type": "string"},
               overwrite={"type": "boolean", "optional": True}), vault_write),
        Tool("vault_append", "Append text to a note (creates it if missing).",
             s(path={"type": "string"}, text={"type": "string"}), vault_append),
        Tool("vault_list", "List note paths, optionally under a folder prefix.",
             s(prefix={"type": "string", "optional": True}), vault_list),
        Tool("remember", "Save a durable fact or decision to today's memory note.",
             s(fact={"type": "string"}), remember),
        Tool("run_python", "Execute Python 3 code in a scratch directory and return stdout/stderr. 30s limit.",
             s(code={"type": "string"}), run_python),
    ]
    return {t.name: t for t in tools}


def call_tool(tools: dict[str, Tool], name: str, args: dict) -> str:
    tool = tools.get(name)
    if not tool:
        return f"error: unknown tool {name}"
    try:
        return tool.fn(**{k: v for k, v in args.items() if not k.startswith("_")})
    except (VaultError, TypeError, OSError) as e:
        return f"error: {e}"
