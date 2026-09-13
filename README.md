# DSS5105 Track 4 - Student Productivity Agent

Status: project collaboration scaffold; the application is not implemented yet.

## Scope

Build a focused student productivity assistant for Outlook / Teams: triage messages, extract deadlines with source references, and propose a weekly plan. Canvas / LMS integration is excluded by the supplied Capstone_Project_Spec_v4.pdf.

Start with synthetic messages and a single end-to-end workflow. Microsoft integration and the technical stack remain team decisions. The separate Capstone_Project_Tracks_v3.pdf has not yet been reviewed.

## Proposed MVP

- Classify messages into actionable categories and explain priority.
- Extract task, due date, time zone, and source; flag missing or ambiguous dates.
- Suggest a weekly plan respecting availability and deadlines.
- Let the student review and correct extracted tasks and plans.
- Present an interface with traceable results and clear failure states.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/` | Application implementation |
| `tests/` | Behaviour and integration tests |
| `data/synthetic/` | Synthetic example messages only |
| `docs/plan.md` | Milestones, ownership and acceptance criteria |
| `docs/evaluation.md` | Evaluation protocol and failure analysis |
| `CONTRIBUTING.md` | Team workflow |
| `.github/` | Issue and pull request templates |

## Getting started

1. Accept the repository collaboration invitation.
2. Clone the repository and create a feature branch.
3. Agree on the MVP and fill the ownership table in `docs/plan.md`.
4. Choose the stack and add installation/run instructions when implementation begins.

There are currently no runtime dependencies or executable application commands.

## Course milestones

Dates below are transcribed from the supplied specification; check course announcements for changes.

| Milestone | Deadline |
| --- | --- |
| Sprint 1 slides | 16 Oct 2026, 15:00; presentation 19:00 |
| Sprint 2 video and slides | 30 Oct 2026, 15:00; presentation 19:00 |
| Sprint 3 video and slides | 13 Nov 2026, 15:00; presentation 19:00 |
| Final submission | 15 Nov 2026, 23:59 |

Use a two-digit group number in submission filenames. Group number: TBD.

Final `GroupNN.zip` contains `Readme.pdf`, `Slide.pdf` or `Slide.pptx`, `Video.mp4`, `Documentation.pdf` (maximum 15 pages), `Evaluation.pdf`, `Teams.pdf`, and `Strategic_Recommendations.pdf`. The specification requires a public GitHub link by Sprint 2 and at final submission. Review repository contents before making it public.

Do not commit credentials, access tokens, real inbox exports or student IDs. Use synthetic data in this repository.
