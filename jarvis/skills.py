"""Skills: repeatable, defined procedures stored as markdown notes in
`Jarvis/Skills/`. Because they live in the vault, you can read and edit them
in Obsidian; a new skill is just a new note with the same frontmatter shape:

    ---
    name: research
    description: one line
    triggers: [research, deep dive on]   # phrases that route a request here
    mode: build                          # brain mode to run under
    save_to: Jarvis/Research/{date} {slug}.md
    fetch_urls: true                     # optional: fetch URLs in the request
    context_k: 8                         # optional: how many vault chunks to retrieve
    ---
    ## Inputs / ## Steps / ## Output format   (the procedure the model must follow)

Invoke explicitly with `/name ...` or implicitly via a trigger phrase.
"""
from __future__ import annotations

import html
import re
import shutil
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .vault import Vault, parse_frontmatter, render_frontmatter, slugify

DEFAULT_SKILLS_DIR = Path(__file__).parent / "default_skills"
URL_RE = re.compile(r"https?://[^\s)>\]]+")


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]
    mode: str
    save_to: str
    procedure: str
    path: str
    fetch_urls: bool = False
    context_k: int = 6
    meta: dict = field(default_factory=dict)

    def matches(self, text: str) -> bool:
        t = text.strip().lower()
        if t.startswith(f"/{self.name.lower()}"):
            return True
        return any(re.search(r"\b" + re.escape(tr.lower()) + r"\b", t) for tr in self.triggers)

    def output_path(self, request: str, now) -> str:
        return self.save_to.format(date=f"{now:%Y-%m-%d}", time=f"{now:%H%M}",
                                   slug=slugify(strip_invocation(request, self.name), 50))


def strip_invocation(text: str, name: str) -> str:
    return re.sub(rf"^\s*/{re.escape(name)}\b\s*", "", text, flags=re.I).strip()


class SkillRegistry:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.dir = vault.root / "Jarvis" / "Skills"
        self.seed_defaults()

    def seed_defaults(self) -> None:
        """Copy the built-in skills into the vault once. Never overwrites user edits."""
        self.dir.mkdir(parents=True, exist_ok=True)
        for src in DEFAULT_SKILLS_DIR.glob("*.md"):
            dst = self.dir / src.name
            if not dst.exists():
                shutil.copyfile(src, dst)

    def load(self) -> list[Skill]:
        skills = []
        for p in sorted(self.dir.glob("*.md")):
            meta, body = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            if not meta.get("name"):
                continue
            triggers = meta.get("triggers") or []
            if isinstance(triggers, str):
                triggers = [triggers]
            skills.append(Skill(
                name=str(meta["name"]), description=str(meta.get("description", "")),
                triggers=[str(t) for t in triggers], mode=str(meta.get("mode", "build")),
                save_to=str(meta.get("save_to", "Jarvis/Inbox/{date} {slug}.md")),
                procedure=body.strip(), path=self.vault.rel(p),
                fetch_urls=bool(meta.get("fetch_urls", False)),
                context_k=int(meta.get("context_k", 6)), meta=meta,
            ))
        return skills

    def match(self, text: str) -> Skill | None:
        skills = self.load()
        # explicit /name wins over trigger phrases
        for s in skills:
            if text.strip().lower().startswith(f"/{s.name.lower()}"):
                return s
        for s in skills:
            if s.matches(text):
                return s
        return None

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.load() if s.name.lower() == name.lower()), None)


def fetch_url_text(url: str, max_chars: int = 8000, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/0.1 (+personal research assistant)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(2_000_000).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def build_skill_prompt(skill: Skill, request: str, context: str, fetched: list[tuple[str, str]]) -> tuple[str, str]:
    system_extra = (
        f"You are executing the skill `{skill.name}`: {skill.description}\n"
        "Follow this procedure exactly. Your final message IS the deliverable, in the output format "
        "below; it will be saved to the vault automatically, so do not save it yourself.\n\n"
        f"{skill.procedure}"
    )
    parts = [f"REQUEST:\n{strip_invocation(request, skill.name)}", f"VAULT CONTEXT:\n{context}"]
    for url, text in fetched:
        parts.append(f"FETCHED SOURCE {url}:\n{text}")
    return system_extra, "\n\n".join(parts)


def save_skill_output(vault: Vault, skill: Skill, request: str, output: str, sources: list[str], now) -> str:
    meta = {"type": f"skill/{skill.name}", "skill": skill.name, "date": f"{now:%Y-%m-%d}",
            "request": strip_invocation(request, skill.name)[:200], "sources": sources}
    return vault.write(skill.output_path(request, now), render_frontmatter(meta) + "\n" + output.strip())
