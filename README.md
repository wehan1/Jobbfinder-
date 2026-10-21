# Jobbfinder

An AI job-search workflow that runs in Claude Code: find postings, evaluate fit honestly, tailor your CV, write cover letters, and prep for interviews, all grounded in your own profile.

It prepares everything. **You** review and send. It never applies for you.

## Setup (10–30 minutes, and it's the part that matters)
1. Clone this repo and open it in Claude Code (`claude` in the repo folder).
2. Fill in, with real facts only:
   - `profile/cv.md`: your full master CV (more detail is better; tailoring cuts it down)
   - `profile/preferences.md`: roles, locations, salary, dealbreakers
   - `profile/stories.md`: 5–8 STAR stories
3. Optional: connect the Indeed connector so `/find-jobs` can search directly.

## Workflow
| Step | Command | Output |
|------|---------|--------|
| Find | `/find-jobs python remote` | Shortlist table |
| Evaluate | `/evaluate <url or pasted posting>` | `applications/<job>/evaluation.md` with a 0–100 fit score |
| Tailor CV | `/tailor-cv <job-folder>` | `applications/<job>/cv.md` |
| Cover letter | `/cover-letter <job-folder>` | `applications/<job>/cover-letter.md` |
| Interview | `/interview-prep <job-folder> technical` | Prep sheet and mock interview |
| Track | `/track` or `/track acme-dev applied` | Pipeline summary |

Rules Claude follows are in `CLAUDE.md`. The most important one is that it never invents experience.

## Privacy
`profile/` and `applications/` contain personal data. If this repo is public, make it private or add them to `.gitignore`.
