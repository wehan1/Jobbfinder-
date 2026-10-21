---
description: Produce a CV tailored to one evaluated job
argument-hint: <application folder name, e.g. acme-backend-developer>
---
Folder: `applications/$ARGUMENTS/`

Read `posting.md` and `evaluation.md` there, plus `profile/cv.md`.

Write `applications/$ARGUMENTS/cv.md`:
- Reorder sections and bullets so the most relevant evidence comes first.
- Rewrite the summary for this role.
- Mirror the posting's terms **only** where the CV already has the matching fact (ATS keywords).
- Cut bullets that don't matter for this job. Max 2 pages' worth.
- **Do not add any fact that is not in `profile/cv.md`.**

After the CV, list under a `<!-- changes -->` comment: what you moved, cut, and reworded, plus any keywords from the posting you could NOT include because the user lacks them.
Write it in the posting's language.
