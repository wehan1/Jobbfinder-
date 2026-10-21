---
description: Search for jobs matching profile/preferences.md and shortlist the best ones
argument-hint: [optional extra query, e.g. "python remote"]
---
Read `profile/preferences.md` and `profile/cv.md`.

Search for jobs matching the target roles and locations, plus this extra query if given: $ARGUMENTS

- If an Indeed connector/tool is available (e.g. `search_jobs`), use it. Otherwise use web search against the job sources listed in preferences.
- Drop anything that hits a dealbreaker. Say how many you dropped and why.
- For the remaining jobs, give a quick fit score from 1 to 5 based only on the CV.

Output a table: Company | Role | Location | Fit (1–5) | One-line reason | Link.
Sort by fit. Then recommend the top 3 to run `/evaluate` on. Do not create application folders yet.
