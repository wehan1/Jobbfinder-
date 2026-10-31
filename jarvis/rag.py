"""Retrieval over the vault.

Design choice: lexical BM25 over heading-aware chunks, zero dependencies, fully
local. For a creator's vault (proper nouns, product names, show titles) lexical
retrieval is a strong baseline, and it never ships your notes to an embedding
API. `Retriever` is the extension point if you later want hybrid/embedding
search: implement `search(query, k)` with the same return type.

The index is refreshed lazily: before each search we stat every note and only
re-chunk files whose mtime changed. A note written by Obsidian a second ago is
searchable on the next request.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .vault import Vault, parse_frontmatter

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-']*")
STOPWORDS = set(
    """a an the and or but if then else of to in on at for from by with about as is are was were be been being
    it its this that these those i me my we our you your he she they them their what which who whom how why when
    where do does did done have has had can could should would will shall may might must not no yes so than too very
    just into over under again further once here there all any both each few more most other some such only own same
    s t don doesn didn isn aren wasn weren up down out off also please tell show give know get got like""".split()
)


def tokenize(text: str) -> list[str]:
    toks = []
    for t in _TOKEN_RE.findall(text.lower()):
        t = t.strip("-'")
        if len(t) < 2 or t in STOPWORDS:
            continue
        # crude plural folding so "hooks" matches "hook"
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        toks.append(t)
    return toks


@dataclass
class Chunk:
    path: str
    heading: str
    text: str
    date: str
    tokens: Counter = field(repr=False, default_factory=Counter)
    length: int = 0


@dataclass
class Hit:
    path: str
    heading: str
    text: str
    date: str
    score: float

    def as_dict(self) -> dict:
        return {"path": self.path, "heading": self.heading, "date": self.date,
                "score": round(self.score, 3), "text": self.text}


def chunk_markdown(body: str, max_chars: int = 1200) -> list[tuple[str, str]]:
    """Split on headings; split long sections on paragraph boundaries."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,6}\s", line):
            sections.append((line.lstrip("#").strip(), []))
        else:
            sections[-1][1].append(line)
    out: list[tuple[str, str]] = []
    for heading, lines in sections:
        text = "\n".join(lines).strip()
        if not text and not heading:
            continue
        paras = re.split(r"\n\s*\n", text) if text else [""]
        buf = ""
        for para in paras:
            if buf and len(buf) + len(para) + 2 > max_chars:
                out.append((heading, buf.strip()))
                buf = ""
            while len(para) > max_chars:
                out.append((heading, para[:max_chars]))
                para = para[max_chars:]
            buf += ("\n\n" if buf else "") + para
        if buf.strip() or heading:
            out.append((heading, buf.strip()))
    return out


class Retriever:
    # BM25 parameters
    K1 = 1.4
    B = 0.75

    def __init__(self, vault: Vault, chunk_chars: int = 1200):
        self.vault = vault
        self.chunk_chars = chunk_chars
        self._files: dict[str, float] = {}
        self._chunks: dict[str, list[Chunk]] = {}
        self._lock = threading.Lock()

    def refresh(self) -> None:
        with self._lock:
            seen = set()
            for rel in self.vault.list_notes():
                seen.add(rel)
                p = self.vault.root / rel
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if self._files.get(rel) == mtime:
                    continue
                self._files[rel] = mtime
                self._chunks[rel] = self._chunk_file(rel, p)
            for rel in list(self._files):
                if rel not in seen:
                    self._files.pop(rel, None)
                    self._chunks.pop(rel, None)

    def _chunk_file(self, rel: str, p: Path) -> list[Chunk]:
        raw = p.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(raw)
        date = self.vault.note_date(rel)
        title = Path(rel).stem
        tags = meta.get("tags", [])
        tag_text = " ".join(tags) if isinstance(tags, list) else str(tags)
        chunks = []
        for heading, text in chunk_markdown(body, self.chunk_chars):
            # title/heading/tags are indexed with the chunk so "the hooks note" finds it
            toks = Counter(tokenize(f"{title} {heading} {tag_text} {text}"))
            chunks.append(Chunk(rel, heading, text, date, toks, sum(toks.values())))
        return chunks

    def search(self, query: str, k: int = 6, exclude_prefixes: tuple[str, ...] = ()) -> list[Hit]:
        self.refresh()
        q = tokenize(query)
        if not q:
            return []
        with self._lock:
            chunks = [c for cs in self._chunks.values() for c in cs
                      if not any(c.path.startswith(px) for px in exclude_prefixes)]
        if not chunks:
            return []
        n = len(chunks)
        avgdl = sum(c.length for c in chunks) / n or 1.0
        df: Counter = Counter()
        qset = set(q)
        for c in chunks:
            for t in qset:
                if t in c.tokens:
                    df[t] += 1
        scored = []
        for c in chunks:
            s = 0.0
            for t in q:
                tf = c.tokens.get(t, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * c.length / avgdl))
            if s > 0:
                scored.append(Hit(c.path, c.heading, c.text, c.date, s))
        scored.sort(key=lambda h: h.score, reverse=True)
        # at most 2 chunks per note so one long note can't crowd out the rest
        out, per_note = [], Counter()
        for h in scored:
            if per_note[h.path] >= 2:
                continue
            per_note[h.path] += 1
            out.append(h)
            if len(out) >= k:
                break
        return out


def format_context(hits: list[Hit], max_chars: int = 6000) -> str:
    if not hits:
        return "(no relevant notes found in the vault)"
    parts, used = [], 0
    for i, h in enumerate(hits, 1):
        head = f"[{i}] {h.path}" + (f" › {h.heading}" if h.heading else "") + f" (dated {h.date})"
        body = h.text.strip()
        piece = f"{head}\n{body}"
        if used + len(piece) > max_chars:
            piece = piece[: max(0, max_chars - used)]
        parts.append(piece)
        used += len(piece)
        if used >= max_chars:
            break
    return "\n\n".join(parts)
