"""The vault: a folder of plain markdown notes that is the single source of truth.

Every front door (web app, Obsidian plugin, CLI) goes through this class, and
this class only ever touches files on disk. Obsidian watches the same folder,
so anything written here shows up in Obsidian immediately, and anything a human
writes in Obsidian is picked up by the next retrieval.

Layout inside the vault:
    Jarvis/Conversations/YYYY-MM-DD.md   every turn, from every front door
    Jarvis/Memory/YYYY-MM-DD.md          explicit "remember ..." facts and decisions
    Jarvis/Inbox/                        quick notes created from the web app
    Jarvis/Research/ Content/ QA/        skill outputs
    Jarvis/Skills/*.md                   skill definitions (editable in Obsidian)
    .jarvis/                             machine state (router log, sandbox); hidden from Obsidian
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path

JARVIS_DIRS = [
    "Jarvis/Conversations",
    "Jarvis/Memory",
    "Jarvis/Inbox",
    "Jarvis/Research",
    "Jarvis/Content",
    "Jarvis/QA",
    "Jarvis/Skills",
]
IGNORED_PARTS = {".obsidian", ".jarvis", ".trash", ".git"}

_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML-frontmatter parser: `key: value`, `key: [a, b]`, and `- item` lists."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    current_list_key = None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if raw.lstrip().startswith("- ") and current_list_key:
            meta[current_list_key].append(_scalar(raw.lstrip()[2:]))
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value == "":
            meta[key] = []
            current_list_key = key
            continue
        current_list_key = None
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [_scalar(v) for v in _split_list(value[1:-1])]
        else:
            meta[key] = _scalar(value)
    return meta, text[m.end():]


def _split_list(inner: str) -> list[str]:
    out, buf, quote = [], "", None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            out.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf)
    return [s.strip() for s in out if s.strip()]


def _scalar(value: str):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def render_frontmatter(meta: dict) -> str:
    if not meta:
        return ""
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: [{', '.join(json.dumps(str(v)) for v in value)}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            s = str(value).replace("\n", " ")
            needs_quote = any(c in s for c in ":#[]{}") or s != s.strip()
            lines.append(f"{key}: {json.dumps(s) if needs_quote else s}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_]+", "-", s)
    return (s[:max_len].rstrip("-")) or "note"


class VaultError(ValueError):
    pass


class Vault:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        for d in JARVIS_DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_dir(self) -> Path:
        return self.root / ".jarvis"

    # ---- path safety -------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        rel = (rel or "").strip().lstrip("/\\")
        if not rel:
            raise VaultError("empty path")
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise VaultError(f"path escapes vault: {rel}")
        if any(part in IGNORED_PARTS for part in p.relative_to(self.root).parts):
            raise VaultError(f"path is in a protected folder: {rel}")
        return p

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    # ---- basic IO ----------------------------------------------------------
    def exists(self, rel: str) -> bool:
        try:
            return self.resolve(rel).exists()
        except VaultError:
            return False

    def read(self, rel: str) -> str:
        p = self.resolve(rel)
        if not p.is_file():
            raise VaultError(f"no such note: {rel}")
        return p.read_text(encoding="utf-8", errors="replace")

    def write(self, rel: str, content: str, overwrite: bool = False) -> str:
        """Write a note. Without overwrite, an existing file gets a numbered sibling."""
        if not rel.lower().endswith(".md"):
            rel += ".md"
        with self._lock:
            p = self.resolve(rel)
            if p.exists() and not overwrite:
                stem, n = p.stem, 2
                while p.exists():
                    p = p.with_name(f"{stem} {n}.md")
                    n += 1
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
            return self.rel(p)

    def append(self, rel: str, text: str, header: str = "") -> str:
        with self._lock:
            p = self.resolve(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            new = not p.exists()
            with p.open("a", encoding="utf-8") as f:
                if new and header:
                    f.write(header)
                f.write(text if text.endswith("\n") else text + "\n")
            return self.rel(p)

    def list_notes(self) -> list[str]:
        out = []
        for p in self.root.rglob("*.md"):
            parts = p.relative_to(self.root).parts
            if any(part in IGNORED_PARTS for part in parts):
                continue
            out.append(p.relative_to(self.root).as_posix())
        return sorted(out)

    def recent_notes(self, n: int = 10) -> list[str]:
        notes = self.list_notes()
        notes.sort(key=lambda r: (self.root / r).stat().st_mtime, reverse=True)
        return notes[:n]

    def find_note(self, name: str) -> str | None:
        """Find a note by exact path, file name, or case-insensitive stem."""
        name = name.strip().strip("[]")
        if self.exists(name) and name.endswith(".md"):
            return name
        target = name.lower().removesuffix(".md")
        for rel in self.list_notes():
            if Path(rel).stem.lower() == target:
                return rel
        return None

    # ---- memory helpers ------------------------------------------------------
    @staticmethod
    def now() -> dt.datetime:
        return dt.datetime.now().astimezone()

    def remember(self, fact: str, source: str = "jarvis") -> str:
        now = self.now()
        rel = f"Jarvis/Memory/{now:%Y-%m-%d}.md"
        header = render_frontmatter({"type": "memory", "date": f"{now:%Y-%m-%d}"}) + f"# Memory {now:%Y-%m-%d}\n\n"
        return self.append(rel, f"- {now:%H:%M} ({source}) {fact.strip()}", header=header)

    def log_turn(self, source: str, user_text: str, reply: str, tier: int, extra: str = "") -> str:
        now = self.now()
        rel = f"Jarvis/Conversations/{now:%Y-%m-%d}.md"
        header = (
            render_frontmatter({"type": "conversation", "date": f"{now:%Y-%m-%d}"})
            + f"# Conversations {now:%Y-%m-%d}\n\n"
        )
        block = (
            f"### {now:%H:%M:%S} · {source} · tier {tier}{(' · ' + extra) if extra else ''}\n\n"
            f"**You:** {user_text.strip()}\n\n"
            f"**Jarvis:** {reply.strip()}\n\n"
        )
        return self.append(rel, block, header=header)

    def note_date(self, rel: str) -> str:
        p = self.resolve(rel)
        try:
            meta, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace")[:2000])
        except OSError:
            meta = {}
        date = meta.get("date") or meta.get("created")
        if date:
            return str(date)[:10]
        return dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
