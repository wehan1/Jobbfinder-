# Jarvis: a personal agentic OS

One assistant for research, content repurposing, and community Q&A. Its memory is an
Obsidian vault, and you can reach it from a web app, from inside Obsidian, or by voice.

This is an independent build of the architecture described in Chase AI's "Claude Agentic OS"
carousel. It does **not** contain the creator's private prompts or configs. Every prompt,
rule, and threshold in this repo is original and meant to be tuned.

```
 web app ─┐                                         ┌─ rules (tier 1, no model)
 Obsidian ┼─▶ (Whisper STT) ─▶ router "Jev" ─▶──────┼─ fast model (tier 2) ──ESCALATE──┐
 CLI ─────┘                                         └─ brain (tier 3) ◀────────────────┘
                                                         ├─ mode: build | code
                                                         └─ skills: research · repurpose · qa
                     ▲  RAG (BM25 over vault)       │ write-back (notes, memory, convo log)
                     └──────── Obsidian vault ◀─────┘ ──▶ (Kokoro TTS)
```

## Quick start

```bash
cp .env.example .env            # set JARVIS_VAULT to your real vault + an API key
python -m jarvis serve          # http://127.0.0.1:8765
python -m jarvis route "build me a launch plan"   # see a routing decision, no model call
python -m jarvis ask "why did we drop that sponsor?"
python -m pytest                # acceptance tests (FakeLLM, no key needed)
```

The core needs only the Python 3.10+ standard library. Voice is optional: `pip install -e '.[voice]'`.

**Obsidian plugin:** `cd obsidian-plugin && npm install && npm run build`, then copy
`manifest.json`, `main.js`, and `styles.css` into `<vault>/.obsidian/plugins/jarvis-agentic-os/`
and enable the plugin. Commands: *Open chat*, *Ask about the current note*, and
*Run /research | /repurpose | /qa on selection*.

## Layers and the decisions behind them

| Layer | File | Decision |
|---|---|---|
| Memory | `jarvis/vault.py` | The vault folder on disk is the only store. Every turn from every door is appended to `Jarvis/Conversations/<date>.md`. Facts go to `Jarvis/Memory/<date>.md`. Machine state lives in `.jarvis/`, which Obsidian hides. |
| RAG | `jarvis/rag.py` | BM25 over heading-aware chunks (1,200 chars, at most 2 chunks per note, k=6). No embedding model: it adds no dependencies, keeps notes off any API, and handles the proper nouns creators use. The index rebuilds changed files by mtime before every search, so a note edited in Obsidian is searchable on the next request. |
| Router | `jarvis/router.py`, `rules.py` | Tier 1 is regex rules (time, date, `remember …`, `new note …`, `open note …`, recent notes, skills, greetings), plus your own rules in `.jarvis/rules.json`. Tier 2 vs 3 uses an additive score (hard verbs +3, vault-wide +3, code +2, length, multi-step), with a threshold of 3. A skill match always goes to tier 3. When in doubt the request goes to the fast model, which can answer `[[ESCALATE]]` to hand off, so a wrong route costs one cheap call. Every decision, with its features, goes to `.jarvis/router.jsonl` for tuning. Overrides: `/deep`, `/quick`, `/code`, `/build`. |
| Brain | `jarvis/brain.py` | One frontier model and two profiles. **build** (the "Claude Code mode"): vault tools, multi-step work. **code** (the "Codex mode"): adds `run_python`. The tool loop is OpenAI-format function calling, capped at 8 steps. |
| Skills | `jarvis/skills.py`, `Jarvis/Skills/*.md` | Each skill is a markdown note with frontmatter (`triggers`, `mode`, `save_to`, `fetch_urls`, `context_k`) and a body with Inputs, Steps, and Output format sections. They're seeded into the vault once and never overwritten, so you edit them in Obsidian. To add a skill, add a note. |
| Voice | `jarvis/voice.py` | faster-whisper (or openai-whisper as a fallback) and Kokoro, both loaded lazily and run locally. Voice requests go through the same `handle()` as text. |
| Front doors | `jarvis/server.py` + `web/index.html`, `obsidian-plugin/` | Both use the same HTTP API. Neither keeps any memory of its own. On load, the plugin checks that the server's vault path is the vault it's running in, and shows a warning if not. |

## Security defaults

- With no token set, the server binds to loopback only. It refuses to bind anything else without `JARVIS_TOKEN`.
- With no token, it also rejects requests whose Host header isn't localhost (this blocks DNS rebinding), and it requires `Content-Type: application/json`, so other websites can't send simple cross-site POSTs.
- Vault paths can't escape the vault or write into `.obsidian/` or `.jarvis/`.
- **`run_python` is off by default.** It's a subprocess with a timeout, not a sandbox. Notes and fetched web pages can carry prompt injection, so turn it on only if you accept that the model can run code as your user.

## What's verified and what isn't

- ✅ 23 acceptance tests (`tests/test_acceptance.py`): typed and voice-transcript requests through all 3 tiers, escalation, mode selection, answering from a note dated 11 days earlier among noise, all 3 skills run twice without clobbering, notes created on the web visible on disk and vice versa, both doors sharing one conversation log, path safety, cross-site POST rejection, and tool write-back.
- ✅ Live against OpenRouter: tier 1 in 0 ms, tier 2 (Haiku 5.5) answering from an old note in about 1 s, tier 3 (Opus 5.5) calling `remember` and writing to the vault, and the `qa` skill end to end over HTTP.
- ✅ The Obsidian plugin type-checks and bundles. ⚠️ It has not been loaded inside a running Obsidian.
- ⚠️ **Voice hasn't been run with real models.** Whisper and Kokoro weren't installed in the build environment. The code follows their public APIs, and the voice path is tested with a stubbed transcriber.
