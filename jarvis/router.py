"""The router ("Jev"): triage every request into exactly one of three tiers
before any model is called.

  1 rules      deterministic handler, no model call
  2 fast       cheap model, single call, no tools
  3 real work  frontier model, tools, skills

Tier 2 vs 3 is a transparent additive score (see `score()`); every decision is
appended to `<vault>/.jarvis/router.jsonl` with its features so you can tune
the weights and threshold from real traffic. When uncertain, the fast model is
allowed to bail out with ESCALATE (see core.py), so a mis-route costs one cheap
call, not a wrong answer.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

from .rules import BUILTIN, Rule, load_user_rules
from .skills import SkillRegistry
from .vault import Vault

HARD_VERBS = re.compile(
    r"(?i)\b(build|implement|refactor|debug|fix (the|my|this)|write (a|an|the|me)? ?(script|program|function|plan|essay|"
    r"outline|article|newsletter|thread|post)|analy[sz]e|compare|strategy|strategi[sz]e|plan out|design|architect|"
    r"draft|summari[sz]e (all|every|my)|go through|audit|review (my|the|this)|step[- ]by[- ]step|figure out)\b")
CODE_HINTS = re.compile(r"(?i)```|\btraceback\b|\bstack ?trace\b|\berror:|\bexception\b|\bregex\b|\bsql\b|"
                        r"\bpython\b|\bjavascript\b|\btypescript\b|\bbash\b|\bcsv\b|\bjson\b|\bapi\b|\bcode\b|"
                        r"\bscript\b|\bcalculate\b|\bcompute\b")
MULTI_STEP = re.compile(r"(?im)^\s*(\d+[.)]|[-*])\s+|\b(and then|after that|then also|first,.*then)\b")
VAULT_WIDE = re.compile(r"(?i)\b(all (my|of my) notes|across (my )?(the )?vault|everything I('ve)? (wrote|written|noted))\b")


@dataclass
class Route:
    tier: int
    reason: str
    rule: str = ""
    skill: str = ""
    mode: str = "build"
    score: int = 0
    features: dict = field(default_factory=dict)
    text: str = ""  # request with routing prefixes removed


class Router:
    def __init__(self, vault: Vault, skills: SkillRegistry, threshold: int = 3):
        self.vault = vault
        self.skills = skills
        self.threshold = threshold

    @property
    def rules(self) -> list[Rule]:
        # user rules first so they can override built-ins
        return load_user_rules(self.vault) + BUILTIN

    def score(self, text: str) -> tuple[int, dict]:
        f = {
            "long": len(text) > 400,
            "very_long": len(text) > 1500,
            "hard_verb": bool(HARD_VERBS.search(text)),
            "code": bool(CODE_HINTS.search(text)),
            "multi_step": bool(MULTI_STEP.search(text)),
            "vault_wide": bool(VAULT_WIDE.search(text)),
            "questions": text.count("?") >= 3,
        }
        weights = {"long": 1, "very_long": 2, "hard_verb": 3, "code": 2, "multi_step": 1,
                   "vault_wide": 3, "questions": 1}
        return sum(weights[k] for k, v in f.items() if v), f

    def route(self, text: str, force_mode: str | None = None) -> Route:
        raw = text.strip()
        forced_tier = None
        mode = force_mode
        # explicit prefixes, may be combined: "/deep /code ..."
        while True:
            m = re.match(r"(?i)^/(deep|quick|code|build)\b\s*", raw)
            if not m:
                break
            word = m.group(1).lower()
            if word == "deep":
                forced_tier = 3
            elif word == "quick":
                forced_tier = 2
            else:
                mode, forced_tier = word, forced_tier or 3
            raw = raw[m.end():]

        if forced_tier is None:
            for rule in self.rules:
                if rule.pattern.search(raw):
                    return Route(1, f"rule:{rule.name}", rule=rule.name, text=raw)

        skill = self.skills.match(raw) if forced_tier != 2 else None
        score, feats = self.score(raw)
        if mode is None:
            mode = skill.mode if skill else ("code" if feats["code"] else "build")
        if skill:
            return Route(3, f"skill:{skill.name}", skill=skill.name, mode=mode, score=score, features=feats, text=raw)
        if forced_tier:
            return Route(forced_tier, "forced", mode=mode, score=score, features=feats, text=raw)
        if score >= self.threshold:
            return Route(3, f"score {score}>={self.threshold}", mode=mode, score=score, features=feats, text=raw)
        return Route(2, f"score {score}<{self.threshold}", mode=mode, score=score, features=feats, text=raw)

    def log(self, route: Route, source: str, final_tier: int, latency_ms: int, model: str = "",
            escalated: bool = False, error: str = "") -> None:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": source, "routed_tier": route.tier,
               "final_tier": final_tier, "escalated": escalated, "model": model, "latency_ms": latency_ms,
               "error": error, **{k: v for k, v in asdict(route).items() if k != "text"},
               "text": route.text[:300]}
        with (self.vault.state_dir / "router.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
