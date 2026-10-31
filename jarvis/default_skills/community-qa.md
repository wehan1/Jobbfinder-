---
name: qa
description: Answer a recurring audience question from vault knowledge and keep a reusable FAQ entry.
triggers: [community question, someone asked, audience asked, a follower asked, viewer asked, faq]
mode: build
save_to: Jarvis/QA/{slug}.md
context_k: 8
---
## Inputs
- The audience question (and optionally who asked / where).
- VAULT CONTEXT: prior answers, notes, and decisions.

## Steps
1. Search the vault for an existing answer (`vault_search` in `Jarvis/QA` and elsewhere). Reuse it if one exists.
2. Answer ONLY from the vault. If the vault doesn't support an answer, say exactly what's missing and draft
   a holding reply instead of guessing.
3. Write in the creator's voice, short enough to paste into a comment or DM.

## Output format
# Q: <question, normalised>
**Answer (paste-ready):**
<2–6 sentences>
**Longer version:**
<optional detail>
**Grounded in:** [[note]] …
**Confidence:** high | medium | low — <why>
