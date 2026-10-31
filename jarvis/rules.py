"""Tier 1: deterministic handlers. No model call, ever.

Built-in rules live here. User rules go in `<vault>/.jarvis/rules.json`:
    [{"name": "studio-hours", "pattern": "(?i)when is the studio open", "response": "Mon-Fri 9-5"}]
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .vault import Vault


@dataclass
class Rule:
    name: str
    pattern: re.Pattern
    handler: Callable[[re.Match, "RuleContext"], str]


@dataclass
class RuleContext:
    vault: Vault
    skills_summary: Callable[[], str]
    source: str


def _time(m, ctx):
    return ctx.vault.now().strftime("It's %H:%M (%Z).")


def _date(m, ctx):
    return ctx.vault.now().strftime("Today is %A, %B %d, %Y.")


def _remember(m, ctx):
    fact = m.group("fact").strip().rstrip(".")
    rel = ctx.vault.remember(fact, source=ctx.source)
    return f"Saved to memory: “{fact}” → {rel}"


def _note(m, ctx):
    title = m.group("title").strip()
    body = (m.group("body") or "").strip()
    now = ctx.vault.now()
    rel = ctx.vault.write(f"Jarvis/Inbox/{title}.md",
                          f"---\ntype: note\ndate: {now:%Y-%m-%d}\nsource: {ctx.source}\n---\n# {title}\n\n{body}\n")
    return f"Created note {rel}"


def _open(m, ctx):
    rel = ctx.vault.find_note(m.group("name"))
    if not rel:
        return f"I couldn't find a note named “{m.group('name').strip()}”."
    text = ctx.vault.read(rel)
    return f"**{rel}**\n\n{text[:3000]}" + ("\n…" if len(text) > 3000 else "")


def _recent(m, ctx):
    notes = ctx.vault.recent_notes(10)
    return "Most recently changed notes:\n" + "\n".join(f"- {n}" for n in notes)


def _skills(m, ctx):
    return ctx.skills_summary()


def _greet(m, ctx):
    return "Hey. What are we working on?"


def _thanks(m, ctx):
    return "Anytime."


def _help(m, ctx):
    return ("Things I handle instantly: time/date, `remember <fact>`, `new note <title>: <body>`, "
            "`open note <name>`, `recent notes`, `list skills`.\n"
            "Skills: `/research <topic>`, `/repurpose <content or note name>`, `/qa <question>`.\n"
            "Prefix `/deep` to force the frontier model, `/quick` to force the fast model, "
            "`/code` for code-execution mode.")


BUILTIN: list[Rule] = [
    Rule("time", re.compile(r"(?i)^\s*(what('?s| is) the time|what time is it)\??\s*$"), _time),
    Rule("date", re.compile(r"(?i)^\s*(what('?s| is) (today'?s )?(the )?date( today)?|what day is (it|today))\??\s*$"), _date),
    Rule("remember", re.compile(r"(?is)^\s*(please\s+)?(remember(?!\s+(when|what|how|if|whether|who|why|where)\b)( that)?[:\s]+|note( that)?:\s*|note that\s+)(?P<fact>.+)$"), _remember),
    Rule("new_note", re.compile(r"(?is)^\s*(new|create( a)?) note\s+(?P<title>[^:\n]{1,80})(:\s*(?P<body>.*))?$"), _note),
    Rule("open_note", re.compile(r"(?i)^\s*(open|show)( me)?( the)? note\s+(?P<name>.+?)\s*$"), _open),
    Rule("recent", re.compile(r"(?i)^\s*(recent|latest) notes\s*$"), _recent),
    Rule("skills", re.compile(r"(?i)^\s*(list|show)( (me|my|the))? skills\s*$|^\s*what skills"), _skills),
    Rule("help", re.compile(r"(?i)^\s*(/?help|what can you do\??)\s*$"), _help),
    Rule("greet", re.compile(r"(?i)^\s*(hi|hey|hello|yo|good (morning|afternoon|evening))( jarvis)?[!. ]*$"), _greet),
    Rule("thanks", re.compile(r"(?i)^\s*(thanks|thank you|thx|cheers)( jarvis)?[!. ]*$"), _thanks),
]


def load_user_rules(vault: Vault) -> list[Rule]:
    path = vault.state_dir / "rules.json"
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rules = []
    for it in items:
        try:
            response = str(it["response"])
            rules.append(Rule(str(it["name"]), re.compile(it["pattern"]), lambda m, ctx, r=response: r))
        except (KeyError, re.error):
            continue
    return rules
