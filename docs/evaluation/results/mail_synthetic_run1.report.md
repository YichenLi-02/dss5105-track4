# Mail evaluation - mail_synthetic_run1

Answer key: mail_eval_v1, 80 mails. Label status: **checked by a person**.

Run: model `gpt-6-luna`, prompt `p00-p02.v1`, schema `mail_analysis.v6`, code `14f3950`, 2026-11-10T10:39:05+00:00. Model time 634.8 s for 80 mails; tokens in 60490, out 52133. Outbound requests refused: 0.

## Triage

| Label | Precision | Recall | F1 | TP | FP | FN | TN | Keyword baseline F1 |
|---|---|---|---|---|---|---|---|---|
| needs_reply | 85.7% (12/14, 95% CI 60%-96%) | 92.3% (12/13, 95% CI 67%-99%) | 0.889 | 12 | 2 | 1 | 65 | 0.828 |
| needs_action | 54.2% (32/59, 95% CI 42%-66%) | 100.0% (32/32, 95% CI 89%-100%) | 0.703 | 32 | 27 | 0 | 21 | 0.708 |

- Both labels right: 65.0% (52/80, 95% CI 54%-74%); keyword baseline 73.8% (59/80, 95% CI 63%-82%).
- Mails that need nothing and were left alone: 52.5% (21/40, 95% CI 38%-67%).
- Mails that need attention but were marked ignore: 0.0% (0/40, 95% CI 0%-9%).
- Category: 93.8% (75/80, 95% CI 86%-97%); always guessing the largest category 37.5% (30/80, 95% CI 28%-48%).
- Mails with no model output: 0 

Reply / action / ignore (rows: answer key, columns: system)

| | reply | action | reply+action | ignore | no output |
|---|---|---|---|---|---|
| **reply** | 0 | 0 | 8 | 0 | 0 |
| **action** | 0 | 27 | 0 | 0 | 0 |
| **reply+action** | 0 | 1 | 4 | 0 | 0 |
| **ignore** | 0 | 17 | 2 | 21 | 0 |

Category (rows: answer key, columns: system)

| | academic | career | events | promotions | other | no output |
|---|---|---|---|---|---|---|
| **academic** | 30 | 0 | 0 | 0 | 0 | 0 |
| **career** | 1 | 11 | 0 | 0 | 0 | 0 |
| **events** | 0 | 0 | 10 | 0 | 0 | 0 |
| **promotions** | 1 | 0 | 0 | 9 | 0 | 0 |
| **other** | 2 | 0 | 1 | 0 | 15 | 0 |

By category

| category | Both labels right | Category right |
|---|---|---|
| academic | 73.3% (22/30, 95% CI 56%-86%) | 100.0% (30/30, 95% CI 89%-100%) |
| career | 58.3% (7/12, 95% CI 32%-81%) | 91.7% (11/12, 95% CI 65%-98%) |
| events | 40.0% (4/10, 95% CI 17%-69%) | 100.0% (10/10, 95% CI 72%-100%) |
| other | 72.2% (13/18, 95% CI 49%-88%) | 83.3% (15/18, 95% CI 61%-94%) |
| promotions | 60.0% (6/10, 95% CI 31%-83%) | 90.0% (9/10, 95% CI 60%-98%) |

By difficulty

| difficulty | Both labels right | Category right |
|---|---|---|
| easy | 66.7% (20/30, 95% CI 49%-81%) | 93.3% (28/30, 95% CI 79%-98%) |
| hard | 85.0% (17/20, 95% CI 64%-95%) | 90.0% (18/20, 95% CI 70%-97%) |
| medium | 50.0% (15/30, 95% CI 33%-67%) | 96.7% (29/30, 95% CI 83%-99%) |

By language

| language | Both labels right | Category right |
|---|---|---|
| en | 64.7% (44/68, 95% CI 53%-75%) | 92.6% (63/68, 95% CI 84%-97%) |
| zh | 66.7% (8/12, 95% CI 39%-86%) | 100.0% (12/12, 95% CI 76%-100%) |

## Deadlines

Answer key: 39 required deadlines, written 41 times in 39 mails; 50 times that are not student work, 6 optional dates, 2 due dates inside receipts.
System: 84 tasks, 75 open (63 with a date, 12 without), 9 closed. Analysis failed on 0 mail(s).

| Measure | System | Regex baseline |
|---|---|---|
| Recall, each mail on its own (stated date extracted) | 97.6% (40/41, 95% CI 87%-100%) | 56.1% (23/41, 95% CI 41%-70%) |
| Recall, unique deadlines with their final date | 97.4% (38/39, 95% CI 87%-100%) | 56.4% (22/39, 95% CI 41%-71%) |
| Precision, each mail on its own | 60.3% (38/63, 95% CI 48%-72%) | 59.0% (23/39, 95% CI 43%-73%) |
| Precision of the task list (duplicates and outdated dates count as wrong) | 57.1% (36/63, 95% CI 45%-69%) | 56.4% (22/39, 95% CI 41%-71%) |

- Second reading (added after the first results): if 'attend <event>' tasks were accepted as tasks (17 of them), precision would be 87.3% (55/63, 95% CI 77%-93%) per mail and 84.1% (53/63, 95% CI 73%-91%) for the task list.
- Missed deadlines by reason: {'wrong_date': 1}
- Open tasks by outcome: {'stale': 2, 'correct': 38, 'wrong_date': 1, 'undated_spurious': 7, 'optional_promoted': 6, 'undated_extra': 2, 'non_task_promoted': 18, 'duplicate_in_mail': 1}
- Closed tasks by outcome: {'not_open': 9}
- Times that are not student work turned into open tasks: 18/50
  - event_time: 17/22
  - phishing_threat: 1/1
- Optional dates turned into open tasks: 6/6
- Receipts re-opened as work: 0/2
- Time of day on correctly dated tasks: {'time_as_expected': 40}
- Time zone on correctly dated tasks: {'stated_and_right': 3, 'none_stated_none_given': 37}

Recall (each mail on its own) by difficulty

| difficulty | Recall |
|---|---|
| easy | 100.0% (7/7, 95% CI 65%-100%) |
| hard | 93.8% (15/16, 95% CI 72%-99%) |
| medium | 100.0% (18/18, 95% CI 82%-100%) |

Recall (each mail on its own) by language

| language | Recall |
|---|---|
| en | 97.2% (35/36, 95% CI 86%-100%) |
| zh | 100.0% (5/5, 95% CI 57%-100%) |

Recall (each mail on its own) by category

| category | Recall |
|---|---|
| academic | 95.7% (22/23, 95% CI 79%-99%) |
| career | 100.0% (6/6, 95% CI 61%-100%) |
| events | 100.0% (2/2, 95% CI 34%-100%) |
| other | 100.0% (10/10, 95% CI 72%-100%) |

Recall (each mail on its own) by tag

| tag | Recall |
|---|---|
| boundary | 100.0% (3/3, 95% CI 44%-100%) |
| later_updated | 100.0% (2/2, 95% CI 34%-100%) |
| multi_deadline | 100.0% (3/3, 95% CI 44%-100%) |
| needs_academic_calendar | 100.0% (1/1, 95% CI 21%-100%) |
| no_time | 100.0% (19/19, 95% CI 83%-100%) |
| relative_date | 100.0% (10/10, 95% CI 72%-100%) |
| repeat_mention | 100.0% (2/2, 95% CI 34%-100%) |
| response_deadline | 100.0% (7/7, 95% CI 65%-100%) |
| timezone | 100.0% (2/2, 95% CI 34%-100%) |
| two_dates | 100.0% (2/2, 95% CI 34%-100%) |
| update | 100.0% (1/1, 95% CI 21%-100%) |
| weekday_date_conflict | 0.0% (0/1, 95% CI 0%-79%) |

## Data minimisation

Addresses, links, phone numbers, codes and long IDs removed before storage: 96.2% (25/26, 95% CI 81%-99%).
Still present: [{'mail': 'synO01', 'kind': 'number or code'}]

## Every error

Triage (33):

- `synA09` expected ignore / academic, got action / academic - DAT5310 Assignment 1 grades are released; log in to the course portal to view the score and feedback.
- `synA10` expected ignore / academic, got action / academic - If you believe Assignment 1 was graded incorrectly, you may request a regrade by October 21; your score may go up or down.
- `synA12` expected reply / academic, got reply+action / academic - Please reply by tomorrow evening whether you can handle capstone data cleaning.
- `synA15` expected ignore / academic, got action / academic - Tomorrow’s lecture will be held in LT12 from 14:00–16:00.
- `synA19` expected ignore / academic, got action / academic - Please complete the voluntary and anonymous mid-semester feedback survey by 25 October.
- `synA23` expected reply+action / academic, got action / academic - Please check and send the list of students who still do not have a project group by Friday.
- `synA27` expected reply / academic, got reply+action / academic - Please report the project group’s dataset choice by Wednesday.
- `synA30` expected ignore / academic, got action / academic - The consultation is confirmed for October 29 at 16:30 in the office.
- `synC01` expected ignore / career, got action / career - Northwind Consulting is hiring 2027 graduate Data Analysts; applications close on 2026-10-31.
- `synC02` expected reply / career, got reply+action / career - Harborlight Insurance invites you to a first-round video interview for the Data Analyst Intern role and asks you to share your availability for November 3–5 by October 30.
- `synC04` expected reply / career, got reply+action / career - They propose two times for a mock interview and ask you to choose one and reply.
- `synC08` expected ignore / career, got action / career - Received 5 matching job openings; the Business Intelligence Intern role lists an application deadline of November 20.
- `synC10` expected reply / career, got reply+action / career - The recruiter invites the user to an online data analyst internship interview and asks for confirmation by November 5.
- `synC12` expected ignore / career, got ignore / academic - The transcript was received and filed; no further action is needed for now, and they will follow up after 9 November.
- `synE02` expected ignore / events, got reply+action / events - Invited to a Capstone sync on October 16, 2026, with an option to RSVP.
- `synE03` expected ignore / events, got action / events - Lakeside Hackathon runs November 7–8; interested participants should register a team by October 30.
- `synE07` expected ignore / events, got action / events - The autumn welcome party is on October 24; interested students should register by Thursday.
- `synE08` expected ignore / events, got reply+action / events - The Capstone sync was moved to 2026-10-19 at 10:00; RSVP is requested.
- `synE09` expected reply / events, got reply+action / events - Invited to speak on the alumni networking night panel; reply by 6 November whether you can join.
- `synE10` expected ignore / events, got action / events - The Intro to dbt webinar starts today at 20:00 Singapore time.
- `synP01` expected ignore / promotions, got action / promotions - Get 40% off the SkillForge annual plan for a limited time; the offer ends at midnight on 2026-10-18.
- `synP03` expected ignore / promotions, got ignore / academic - A machine learning newsletter covers evaluation-set leakage, feature stores, and gradient-boosted tree calibration.
- `synP05` expected ignore / promotions, got action / promotions - Meridian Student Card promotion: apply by 2026-11-30 and spend S$500 in the first two months to receive S$200 cashback.
- `synP06` expected ignore / promotions, got action / promotions - The 35% scholarship discount for the DataPro Data Science Bootcamp expires tonight; confirm a seat to lock it in.
- `synP09` expected ignore / promotions, got action / promotions - The email promotes a limited-time offer to upgrade to a 5G Unlimited plan.
- `synO02` expected ignore / other, got action / other - Lakeside detected a new sign-in; if it wasn’t you, reset your password immediately.
- `synO07` expected reply / other, got reply+action / other - Choose an air-con repair date by Friday and ensure someone is in the room during the visit.
- `synO08` expected action / other, got action / academic - The Student's Pass expires on 2026-11-30; submit a renewal application by 2026-11-16 and upload the acknowledgement to the student portal.
- `synO09` expected ignore / other, got ignore / academic - The course portal will be under maintenance on October 25 from 02:00 to 06:00; submissions will be unavailable, and no deadlines fall during that period.
- `synO10` expected ignore / other, got action / other - The email claims the mailbox will be deactivated and asks for a password; it may be phishing.
- `synO13` expected reply / other, got reply+action / other - Reply YES by October 23, 2026, to keep the October 26 University Health Centre appointment.
- `synO14` expected action / other, got action / events - Please clear the area around the air-conditioning unit and window before the October 29 inspection; you do not need to be present.
- `synO16` expected ignore / other, got action / other - An online payment of RMB 268 was charged to the account ending in 1234 on October 28; contact the bank if you did not make it.

Deadlines (36):

- `synA06` wrong_date: expected [None] ['18:00', None] ("due Thursday, 23 October at 6 pm"); got 2026-10-23 18:00 "提交 Lab 3 报告及 Docker Compose 文件" [pending]
- `synA01` stale: task "Complete and submit Assignment 2" 2026-10-30 23:59 from deadline "due on Friday, 30 October 2026 at 23:59 (SGT)"
- `synA02` stale: task "Submit Assignment 2" 2026-10-30 23:59 from deadline "due this Friday at 23:59"
- `synA06` wrong_date: task "Submit the Lab 3 report and Docker Compose file" 2026-10-23 18:00 from deadline "due Thursday, 23 October at 6 pm"
- `synA09` undated_spurious: task "View DAT5310 Assignment 1 grade and feedback" None None
- `synA10` optional_promoted: task "Submit an Assignment 1 regrade request" 2026-10-21 None from optional "submit a regrade request through the portal by 21 October"
- `synA15` non_task_promoted: task "Attend the lecture in the new venue" 2026-10-21 14:00 from non_task/event_time "Wednesday, 21 October, 14:00-16:00"
- `synA18` non_task_promoted: task "Attend the online task-allocation meeting" 2026-10-20 20:00 from non_task/event_time "明晚8点"
- `synA19` optional_promoted: task "Complete the mid-semester feedback survey" 2026-10-25 None from optional "The survey closes on 25 October"
- `synA20` non_task_promoted: task "Attend office hours" 2026-11-05 15:00 from non_task/event_time "Thursday 3-4 pm"
- `synA30` non_task_promoted: task "Attend consultation" 2026-10-29 16:30 from non_task/event_time "Thursday, 29 October, 4:30 pm"
- `synC01` optional_promoted: task "Apply for a 2027 graduate Data Analyst role" 2026-10-31 None from optional "Applications close on 31 October 2026"
- `synC04` non_task_promoted: task "Confirm mock interview time (Thursday option)" 2026-10-22 19:00 from non_task/event_time "Thursday 22 October at 7 pm"
- `synC04` non_task_promoted: task "Confirm mock interview time (Saturday option)" 2026-10-24 10:00 from non_task/event_time "Saturday 24 October at 10 am"
- `synC08` optional_promoted: task "Business Intelligence Intern, Solace Retail" 2026-11-20 None from optional "apply by 20 November"
- `synC08` undated_spurious: task "Data Science Intern, Brightwave Energy" None None
- `synC08` undated_spurious: task "Analytics Intern, Pemberton Logistics" None None
- `synC08` undated_spurious: task "Junior Data Engineer, Quillon Health" None None
- `synC08` undated_spurious: task "Research Assistant (part-time), Lakeside Policy Lab" None None
- `synC09` non_task_promoted: task "Attend CV review appointment" 2026-10-27 14:00 from non_task/event_time "Tuesday, 27 October at 2 pm"
- `synC10` non_task_promoted: task "Data Analyst Internship Online Interview" 2026-11-10 14:00 from non_task/event_time "11月10日下午2点"
- `synE01` non_task_promoted: task "Causal ML in Practice Seminar" 2026-10-22 16:00 from non_task/event_time "Thursday, 22 October, 4:00-5:00 pm"
- `synE02` non_task_promoted: task "Capstone sync meeting" 2026-10-16 15:00 from non_task/event_time "Fri 16 Oct 2026 3pm - 4pm Singapore Standard Time"
- `synE03` optional_promoted: task "Register a hackathon team" 2026-10-30 None from optional "Register your team by 30 October"
- `synE06` non_task_promoted: task "Coffee chat with alumni" 2026-10-21 17:00 from non_task/event_time "Wednesday, 21 October, 5 pm"
- `synE06` non_task_promoted: task "Deepavali celebration" 2026-11-06 18:00 from non_task/event_time "Friday, 6 November, 6 pm"
- `synE06` undated_spurious: task "Badminton social" None None
- `synE07` optional_promoted: task "Register for the Autumn Welcome Party" 2026-10-22 None from optional "请在周四前填写报名表"
- `synE07` non_task_promoted: task "Attend the Autumn Welcome Party" 2026-10-24 15:00 from non_task/event_time "本周六（10月24日）下午3点"
- `synE08` non_task_promoted: task "Capstone sync" 2026-10-19 10:00 from non_task/event_time "Mon 19 Oct 2026 10am - 11am Singapore Standard Time"
- `synE09` non_task_promoted: task "Invitation to speak on the alumni networking night panel" 2026-11-18 None from non_task/event_time "on 18 November"
- `synE10` non_task_promoted: task "Attend the Intro to dbt webinar" 2026-11-03 20:00 from non_task/event_time "today, 8:00 PM SGT"
- `synO02` undated_spurious: task "Reset your password immediately if the sign-in was not yours" None None
- `synO07` non_task_promoted: task "Air-con repair option: 27 October" 2026-10-27 None from non_task/event_time "Tuesday 27 October or Wednesday 28 October, between 2 and 4 pm"
- `synO07` duplicate_in_mail: task "Air-con repair option: 28 October" 2026-10-28 None from non_task/event_time "Tuesday 27 October or Wednesday 28 October, between 2 and 4 pm"
- `synO10` non_task_promoted: task "Reply with the mailbox username and password within 24 hours" None None from non_task/phishing_threat "deactivated on 20 October"
