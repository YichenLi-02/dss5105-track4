# Feature coverage and review

Scope: the team’s first-version workflow of existing messages, task review, study planning, approval, saving and re-planning. This file distinguishes completed frontend interactions from backend work.

## First-version coverage

| Requirement | Frontend behavior | Integration status |
| --- | --- | --- |
| Paste an announcement | Text entry, source, received date and explicit demo mode | Local UI complete |
| CSV import | Multiline quoted fields, source metadata, duplicate-source skipping and invalid-file feedback | Import UI complete; team importer pending |
| Task extraction | Demo-format parser or manual task entry, no automatic invented dates | Actual AI extraction pending |
| Source evidence | Selected task wording and source history | UI complete; real extraction evidence pending |
| Edit tasks | Title, date, time, priority and remaining effort | Local UI complete |
| Missing fields | Needs input state; incomplete tasks cannot enter planning | Local UI complete |
| Duplicate tasks and date changes | Exact-title demo source linking, original and alternative date, explicit student choice | UI complete; semantic matching pending |
| Student confirmation | Confirm selected valid tasks; changes require confirmation again | Local UI complete |
| Free time and fixed events | Separate availability and busy-time editors with validation | Local UI complete; calendar adapter pending |
| Planning | Browser simulation with daily caps, 30–90-minute sessions, breaks and deadlines | Final member 4/5 planner pending |
| Shortage | Per-task missing minutes/hours, with adjustment guidance | Local UI complete |
| Buffer risk and input warnings | Visible warnings, no silent relaxation of hard constraints | Local UI complete |
| Draft versus saved plan | Distinct status; generation does not overwrite saved work | Local UI complete |
| Saving and restoration | Explicit confirmation, version check, local storage and reload | Server persistence pending |
| Save failure | Previous saved data remains intact; draft stays available | Local UI complete |
| Re-planning | Preserve locks; flag conflicting locked sessions | Local UI complete |
| Progress | Confirm completion, reduce remaining effort, advance demo clock, retain daily completed load | Local UI complete; service integration pending |
| External effects | No automatic email, meeting or calendar write | Future writes need separate confirmation |

## Broader Track 4 scope

The instructor’s track also lists inbox triage and reply drafts, meeting/thread summaries and follow-ups, and direct Outlook/Teams/calendar integration. Those are not implemented by these three pages. The team’s current README prioritizes the message-to-task-to-plan workflow. If the team includes the other capabilities in its final agreed scope, it must add their UI flows and backend implementations. This prototype must not be presented as covering all Track 4 capabilities.

Canvas/LMS integration is excluded.

## Interaction review

- Selected tasks and the currently inspected source row are separate concepts.
- Confirmation completes only valid tasks. Incomplete candidates remain visible.
- A new deadline proposal needs a choice; neither source is silently discarded.
- An edited deadline or effort invalidates the previous confirmation and draft.
- Availability and fixed events use separate editors to avoid accidental class conflicts.
- Generate, adopt/save and complete are different actions and different states.
- Re-planning gives a fresh preview. Locks cannot be silently moved to hide a conflict.
- Completed sessions reduce remaining effort and contribute to their day’s load.
- Save confirmation shows old/new amounts and counts moved or removed sessions.
- Error messages preserve current data and offer a next step.

## Visual review

The interface uses a consistent purple accent, white content surfaces and a muted background. Sidebar navigation keeps all three stages visible. Primary actions share a color and position. Source evidence appears beside editable tasks. Per-day sessions use task colors without relying on color alone. Fields have accessible labels, dialogs use native modal focus behavior, and the layout adapts to narrower screens.

All built-in UI copy, source comments, documentation, slide text, slide notes and speaking scripts are English. Imported user text is preserved in its original language. Operating-system file dialogs follow the user’s operating-system language; the app’s visible file button and date fields remain English.

## Verification completed

Browser checks covered the normal three-page flow, empty input, incomplete deadlines, no scheduling for unconfirmed tasks, no overlap, daily focus limits, sessions of 30–90 minutes, deadlines, lock retention, lock conflicts, completed work accounting, six-hour shortage, changed-date choice, duplicate CSV import, invalid settings, save failure, saving/reloading and mobile horizontal overflow. No uncaught JavaScript errors appeared in the tested flows.

This is functional frontend verification, not a student usability study or an independent system evaluation. Real extraction, hidden evaluation sets, actual privacy controls and final backend recovery must be tested after integration.
