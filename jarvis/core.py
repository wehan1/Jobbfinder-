"""The orchestrator: one `handle()` that every front door calls.

flow: (voice → Whisper) → router → [rules | fast model | brain (+skill)] → vault write-back → (Kokoro)
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from .brain import Brain
from .config import Config
from .llm import LLM, LLMError, OpenAICompatLLM
from .rag import Hit, Retriever, format_context
from .router import Route, Router
from .rules import RuleContext
from .skills import SkillRegistry, URL_RE, build_skill_prompt, fetch_url_text, save_skill_output
from .tools import build_tools
from .vault import Vault, VaultError
from .voice import STT, TTS

ESCALATE = "[[ESCALATE]]"

FAST_PROMPT = f"""You are Jarvis, a personal assistant for a content creator, answering in fast mode.
Answer briefly and directly using the vault notes below when relevant; cite them as [n].
You have NO tools in this mode and cannot save anything.
If the request needs multi-step work, tool use, writing files, running code, long-form writing,
or you are not confident you can answer correctly, reply with exactly {ESCALATE} and nothing else.
Today is {{today}}.

VAULT NOTES:
{{context}}"""


@dataclass
class Result:
    reply: str
    tier: int
    route: dict
    model: str = ""
    mode: str = ""
    skill: str = ""
    escalated: bool = False
    sources: list[dict] = field(default_factory=list)
    saved: list[str] = field(default_factory=list)
    log_path: str = ""
    latency_ms: int = 0
    transcript: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class Jarvis:
    def __init__(self, config: Config, llm: LLM | None = None):
        self.config = config
        self.vault = Vault(config.vault_path)
        self.retriever = Retriever(self.vault, chunk_chars=config.chunk_chars)
        self.skills = SkillRegistry(self.vault)
        self.router = Router(self.vault, self.skills, threshold=config.tier3_threshold)
        self.llm = llm or OpenAICompatLLM(config.llm_base_url, config.llm_api_key)
        self.tools = build_tools(self.vault, self.retriever, config.allow_code_exec)
        self.brain = Brain(self.llm, self.tools, max_steps=config.max_tool_steps)
        self.stt = STT(config.whisper_model)
        self.tts = TTS(config.kokoro_voice, config.kokoro_lang)

    def handle_voice(self, audio: bytes, suffix: str = ".webm", source: str = "web", **kw) -> Result:
        """Voice is only an input channel: transcribe locally, then the exact same path as text."""
        text = self.stt.transcribe(audio, suffix=suffix)
        result = self.handle(text, source=source, transcript=True, **kw)
        result.transcript = text
        return result

    # ------------------------------------------------------------------
    def handle(self, text: str, source: str = "web", history: list[dict] | None = None,
               mode: str | None = None, context_path: str | None = None, transcript: bool = False) -> Result:
        t0 = time.monotonic()
        text = (text or "").strip()
        if not text:
            return Result("Say something and I'll route it.", 1, {"reason": "empty"})
        route = self.router.route(text, force_mode=mode)
        history = (history or [])[-10:]
        result: Result
        try:
            if route.tier == 1:
                result = self._tier1(route, source)
            else:
                hits = self._retrieve(route, context_path)
                if route.tier == 2:
                    result = self._tier2(route, hits, history)
                    if result.escalated:
                        result = self._tier3(route, hits, history, escalated=True)
                else:
                    result = self._tier3(route, hits, history)
        except (LLMError, VaultError) as e:
            result = Result(f"Something failed: {e}", route.tier, {}, error=str(e))
        result.route = {"tier": route.tier, "reason": route.reason, "rule": route.rule, "skill": route.skill,
                        "mode": route.mode, "score": route.score, "features": route.features}
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        src = f"{source} (voice)" if transcript else source
        extra = " · ".join(x for x in [
            f"skill {result.skill}" if result.skill else "",
            "escalated" if result.escalated else "",
            ", ".join(f"[[{s}]]" for s in result.saved),
        ] if x)
        result.log_path = self.vault.log_turn(src, text, result.reply, result.tier, extra)
        self.router.log(route, src, result.tier, result.latency_ms, result.model, result.escalated, result.error)
        return result

    # ------------------------------------------------------------------
    def _skills_summary(self) -> str:
        skills = self.skills.load()
        if not skills:
            return "No skills defined. Add one under Jarvis/Skills/."
        return "Skills:\n" + "\n".join(
            f"- `/{s.name}` — {s.description} (triggers: {', '.join(s.triggers) or '—'}; saves to `{s.save_to}`)"
            for s in skills)

    def _tier1(self, route: Route, source: str) -> Result:
        rule = next(r for r in self.router.rules if r.name == route.rule)
        m = rule.pattern.search(route.text)
        reply = rule.handler(m, RuleContext(self.vault, self._skills_summary, source))
        saved = [reply.rsplit("→ ", 1)[-1]] if route.rule == "remember" else []
        if route.rule == "new_note":
            saved = [reply.removeprefix("Created note ")]
        return Result(reply, 1, {}, model="rules", saved=saved)

    def _retrieve(self, route: Route, context_path: str | None):
        k = self.config.retrieval_k
        if route.skill:
            sk = self.skills.get(route.skill)
            k = sk.context_k if sk else k
        # don't let skill definitions themselves pollute retrieval
        hits = self.retriever.search(route.text, k=k, exclude_prefixes=("Jarvis/Skills/",))
        if context_path:
            try:
                rel = self.vault.find_note(context_path) or context_path
                body = self.vault.read(rel)
                hits = [Hit(rel, "(current note)", body[:4000], self.vault.note_date(rel), 99.0)] + \
                       [h for h in hits if h.path != rel]
            except VaultError:
                pass
        return hits

    def _sources(self, hits) -> list[dict]:
        return [{"path": h.path, "heading": h.heading, "date": h.date, "score": round(h.score, 3)} for h in hits]

    def _tier2(self, route: Route, hits, history) -> Result:
        model = self.config.fast_model
        system = FAST_PROMPT.format(today=self.vault.now().strftime("%Y-%m-%d"),
                                    context=format_context(hits, 4000))
        resp = self.llm.chat([{"role": "system", "content": system}, *history,
                              {"role": "user", "content": route.text}], model=model, max_tokens=700)
        reply = resp.content.strip()
        if self.config.escalate_from_fast and (reply.startswith(ESCALATE) or (ESCALATE in reply and len(reply) < 60)):
            return Result("", 2, {}, model=model, escalated=True, sources=self._sources(hits))
        return Result(reply, 2, {}, model=model, mode="fast", sources=self._sources(hits))

    def _tier3(self, route: Route, hits, history, escalated: bool = False) -> Result:
        mode = route.mode or "build"
        today = self.vault.now().strftime("%Y-%m-%d")
        skill = self.skills.get(route.skill) if route.skill else None
        if skill:
            mode = route.mode if route.mode in ("build", "code") else skill.mode
        model = self.config.model_for_mode(mode)
        if skill:
            fetched = []
            if skill.fetch_urls:
                for url in URL_RE.findall(route.text)[:5]:
                    try:
                        fetched.append((url, fetch_url_text(url)))
                    except Exception as e:  # network errors must not kill the skill
                        fetched.append((url, f"(fetch failed: {e})"))
            extra, user = build_skill_prompt(skill, route.text, format_context(hits, 8000), fetched)
            br = self.brain.run(mode=mode, model=model, system=self.brain.system_prompt(mode, today, extra),
                                user=user, history=history)
            sources = [h.path for h in hits] + [u for u, _ in fetched]
            saved_rel = save_skill_output(self.vault, skill, route.text, br.reply, sources, self.vault.now())
            reply = br.reply + f"\n\n— saved to [[{saved_rel}]]"
            return Result(reply, 3, {}, model=model, mode=mode, skill=skill.name, escalated=escalated,
                          sources=self._sources(hits), saved=br.saved + [saved_rel])
        extra = "RETRIEVED VAULT NOTES:\n" + format_context(hits, 8000)
        br = self.brain.run(mode=mode, model=model, system=self.brain.system_prompt(mode, today, extra),
                            user=route.text, history=history)
        return Result(br.reply, 3, {}, model=model, mode=mode, escalated=escalated,
                      sources=self._sources(hits), saved=br.saved)
