---
name: research
description: Gather, synthesize, and save findings on a topic, grounded in the vault and any linked sources.
triggers: [research, deep dive on, look into, find out about]
mode: build
save_to: Jarvis/Research/{date} {slug}.md
fetch_urls: true
context_k: 8
---
## Inputs
- A topic or question, optionally with source URLs (they are fetched and supplied as FETCHED SOURCE).
- Retrieved vault notes (VAULT CONTEXT) — what the user already knows and has decided.

## Steps
1. Restate the research question in one sentence.
2. Pull out what the vault already says (cite [n] / note path). Flag any contradictions with fetched sources.
3. Use fetched sources (cite by URL). Use general knowledge only when labelled `(background knowledge, unverified)`.
4. Use `vault_search` / `vault_read` if the supplied context looks incomplete.
5. Separate facts from inferences. Do not fabricate statistics, quotes, or URLs.
6. End with concrete angles the creator could make content about.

## Output format
# Research: <topic>
**Question:** …
## TL;DR
3–5 bullets.
## What the vault already says
## New findings
## Open questions / gaps
## Content angles
## Sources
- vault: [[note name]] …
- web: <url> …
