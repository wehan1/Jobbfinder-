---
description: Build an interview prep sheet for one job
argument-hint: <application folder name> [interview type, e.g. "technical" or "HR screen"]
---
Arguments: $ARGUMENTS (first word is the folder under `applications/`, rest is the interview type).

Read the folder's `posting.md`, `evaluation.md`, `cv.md`, plus `profile/stories.md`. Research the company with web search if available (recent news, product, size, culture signals).

Write `interview-prep.md` in that folder:
1. **Company brief** — 5 bullets, with sources.
2. **10 likely questions** for this interview type, each with: why they'll ask it, which STAR story or CV fact answers it, and a 3-bullet answer outline.
3. **The 3 hardest questions** given the gaps in `evaluation.md`, with honest answer outlines.
4. **5 sharp questions to ask them.**
5. **Salary answer** based on `profile/preferences.md`.

Then offer to run a mock interview: ask one question at a time, wait for the user's answer, and give blunt feedback before the next.
Update `applications/tracker.md` status to `Interviewing`.
