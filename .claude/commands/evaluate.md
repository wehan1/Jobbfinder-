---
description: Score a job posting against your profile, brutally and honestly
argument-hint: <posting URL or pasted text>
---
Job posting: $ARGUMENTS

1. If it's a URL, fetch it. Save the full posting text to `applications/<company>-<role>/posting.md` (kebab-case folder name).
2. Read `profile/cv.md`, `profile/preferences.md`, `profile/stories.md`.
3. Write `applications/<company>-<role>/evaluation.md` with:
   - **Fit score 0–100** and a one-sentence verdict (Apply / Apply with caveats / Skip).
   - **Requirements table:** each stated requirement → Met / Partial / Missing → evidence from the CV (quote it) or "none".
   - **Dealbreaker check** against preferences.
   - **Red flags** in the posting (vague scope, unrealistic requirements, signs of high turnover, missing salary where legally required).
   - **Gaps to address:** what the cover letter or interview must handle head-on.
   - **Which STAR stories to use.**
4. Add or update a row in `applications/tracker.md` with status `Evaluated`.

Be blunt. A 45 is a 45. Never count a skill as Met without evidence in the CV.
