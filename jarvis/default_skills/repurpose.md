---
name: repurpose
description: Turn one piece of content into multiple platform-native formats.
triggers: [repurpose, turn this into, make a thread from, carousel from, clip ideas from]
mode: build
save_to: Jarvis/Content/{date} {slug}.md
context_k: 6
---
## Inputs
- The source content pasted in the request, OR the name of a vault note (use `vault_read` to load it).
- VAULT CONTEXT: look for notes on the creator's voice, audience, and past posts and match them.

## Steps
1. Identify the single core idea and the 3 strongest supporting points of the source.
2. If the source is a note name rather than text, load it with `vault_read` first.
3. Write each format below natively for its platform — do not just shorten the same text.
4. Keep every factual claim traceable to the source. No new claims.

## Output format
# Repurposed: <source title>
**Source:** <note link or "pasted">  ·  **Core idea:** …
## X / Twitter thread
Hook tweet + 5–8 tweets, numbered.
## LinkedIn post
≤ 1,300 characters.
## Instagram carousel
8–10 slides: `Slide n — headline / body`.
## Short-form video script (≤ 60s)
Hook (0–3s), beats, CTA.
## Newsletter blurb
~120 words.
## Titles / hooks
5 options.
