# Sprint 1 speaking script

Presenter: zhengjunduo. Approximate total: 60 seconds at a normal presentation pace. Use slides 1 and 2. Slides 3–5 are appendix screenshots for questions and discussion.

## Slide 1 — An interface students can use

My component is the student interface. It has three connected pages: input messages, review tasks, and study planning. Students can edit deadlines against the original text, add remaining effort, and confirm the tasks they want to schedule. They then set their available hours and preview a plan before saving it.

## Slide 2 — Clear decisions when plans change

The UI also handles missing dates, conflicting deadline suggestions, and insufficient time. Students can lock a session, record completed work, and re-plan the remaining effort. Saving requires a separate confirmation and restores the workspace after a reload. This is a working frontend prototype with demo extraction and scheduling. Next, I will connect the team’s AI and backend services and test usability with students.

## Optional live walkthrough

1. Choose **Normal week**, then click **Review extracted tasks**.
2. Edit a task or use **View** to inspect its original wording.
3. Click **Confirm selected tasks**, then **Generate plan**.
4. Open **Edit hours** to show availability, classes and focus settings.
5. Use **Lock** and **Re-plan** to show a stable session. Use **Done** to record progress in the fictional demo.
6. Click **Adopt and save**, then **Confirm and save**. Reload to demonstrate local restoration.
7. Choose **Missing deadline**, **Not enough time**, or **Deadline change** to explain the corresponding exception.

## Questions to prepare for

**Is the AI system already integrated?**

No. This deliverable implements frontend interactions with a local demo parser and scheduling simulator. Real language extraction and backend integration are the next step.

**What happens when a deadline changes?**

The demo retains both sources and asks the student to choose a date. Confirmation is required again, and the student reviews a new plan before replacing the saved one.

**Does saving write to the student’s calendar?**

No. It stores the demonstration workspace in this browser. Calendar writes, emails and other external actions need separate integration and user confirmation.

**How do you know the interface works?**

The prototype has browser checks for the normal flow, missing fields, time shortages, date changes, progress, locks, saving and reload. These are frontend checks. They do not establish model accuracy or measured time savings, and usability with students is still to be evaluated.
