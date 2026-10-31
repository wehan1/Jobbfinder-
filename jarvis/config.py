"""Configuration, read from environment variables (optionally a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    vault_path: Path
    host: str = "127.0.0.1"
    port: int = 8765
    token: str = ""

    # Any OpenAI-compatible /chat/completions endpoint. OpenRouter by default so
    # one key covers both the fast and the frontier model.
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    fast_model: str = "anthropic/claude-haiku-5.5"
    frontier_model: str = "anthropic/claude-opus-5.5"
    # Per-mode overrides for the brain; empty means "use frontier_model".
    build_model: str = ""
    code_model: str = ""

    # Router
    tier3_threshold: int = 3
    escalate_from_fast: bool = True

    # RAG
    retrieval_k: int = 6
    chunk_chars: int = 1200

    # Brain
    max_tool_steps: int = 8
    allow_code_exec: bool = False

    # Voice
    whisper_model: str = "base.en"
    kokoro_voice: str = "af_heart"
    kokoro_lang: str = "a"

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env_file: str | os.PathLike | None = ".env") -> "Config":
        if env_file:
            _load_dotenv(Path(env_file))
        vault = os.environ.get("JARVIS_VAULT", "./vault")
        return cls(
            vault_path=Path(vault).expanduser().resolve(),
            host=os.environ.get("JARVIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("JARVIS_PORT", "8765")),
            token=os.environ.get("JARVIS_TOKEN", ""),
            llm_base_url=os.environ.get("JARVIS_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            llm_api_key=os.environ.get("JARVIS_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY", ""),
            fast_model=os.environ.get("JARVIS_FAST_MODEL", "anthropic/claude-haiku-5.5"),
            frontier_model=os.environ.get("JARVIS_FRONTIER_MODEL", "anthropic/claude-opus-5.5"),
            build_model=os.environ.get("JARVIS_BUILD_MODEL", ""),
            code_model=os.environ.get("JARVIS_CODE_MODEL", ""),
            tier3_threshold=int(os.environ.get("JARVIS_TIER3_THRESHOLD", "3")),
            escalate_from_fast=_flag("JARVIS_ESCALATE_FROM_FAST", True),
            retrieval_k=int(os.environ.get("JARVIS_RETRIEVAL_K", "6")),
            chunk_chars=int(os.environ.get("JARVIS_CHUNK_CHARS", "1200")),
            max_tool_steps=int(os.environ.get("JARVIS_MAX_TOOL_STEPS", "8")),
            allow_code_exec=_flag("JARVIS_ALLOW_CODE_EXEC", False),
            whisper_model=os.environ.get("JARVIS_WHISPER_MODEL", "base.en"),
            kokoro_voice=os.environ.get("JARVIS_KOKORO_VOICE", "af_heart"),
            kokoro_lang=os.environ.get("JARVIS_KOKORO_LANG", "a"),
        )

    def model_for_mode(self, mode: str) -> str:
        if mode == "code" and self.code_model:
            return self.code_model
        if mode == "build" and self.build_model:
            return self.build_model
        return self.frontier_model
