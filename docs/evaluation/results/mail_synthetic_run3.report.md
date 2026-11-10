# Mail evaluation - mail_synthetic_run3

Answer key: mail_eval_v1, 80 mails. Label status: **correct by construction (written with each mail, frozen before the first run); not yet reviewed by a human**.

Run: model `gpt-6-luna`, prompt `p00-p02.v1`, schema `mail_analysis.v6`, code `14f3950`, 2026-11-10T10:38:51+00:00. Model time 620.9 s for 80 mails; tokens in 60490, out 50094. Outbound requests refused: 0.

## Triage

| Label | Precision | Recall | F1 | TP | FP | FN | TN | Keyword baseline F1 |
|---|---|---|---|---|---|---|---|---|
| needs_reply | 86.7% (13/15, 95% CI 62%-96%) | 100.0% (13/13, 95% CI 77%-100%) | 0.929 | 13 | 2 | 0 | 65 | 0.828 |
| needs_action | 56.1% (32/57, 95% CI 43%-68%) | 100.0% (32/32, 95% CI 89%-100%) | 0.719 | 32 | 25 | 0 | 23 | 0.708 |

- Both labels right: 68.8% (55/80, 95% CI 58%-78%); keyword baseline 73.8% (59/80, 95% CI 63%-82%).
- Mails that need nothing and were left alone: 57.5% (23/40, 95% CI 42%-72%).
- Mails that need attention but were marked ignore: 0.0% (0/40, 95% CI 0%-9%).
- Category: 92.5% (74/80, 95% CI 85%-96%); always guessing the largest category 37.5% (30/80, 95% CI 28%-48%).
- Mails with no model output: 0 

Reply / action / ignore (rows: answer key, columns: system)

| | reply | action | reply+action | ignore | no output |
|---|---|---|---|---|---|
| **reply** | 0 | 0 | 8 | 0 | 0 |
| **action** | 0 | 27 | 0 | 0 | 0 |
| **reply+action** | 0 | 0 | 5 | 0 | 0 |
| **ignore** | 0 | 15 | 2 | 23 | 0 |

Category (rows: answer key, columns: system)

| | academic | career | events | promotions | other | no output |
|---|---|---|---|---|---|---|
| **academic** | 30 | 0 | 0 | 0 | 0 | 0 |
| **career** | 1 | 11 | 0 | 0 | 0 | 0 |
| **events** | 0 | 0 | 10 | 0 | 0 | 0 |
| **promotions** | 1 | 0 | 0 | 9 | 0 | 0 |
| **other** | 2 | 0 | 2 | 0 | 14 | 0 |

By category

| category | Both labels right | Category right |
|---|---|---|
| academic | 76.7% (23/30, 95% CI 59%-88%) | 100.0% (30/30, 95% CI 89%-100%) |
| career | 66.7% (8/12, 95% CI 39%-86%) | 91.7% (11/12, 95% CI 65%-98%) |
| events | 40.0% (4/10, 95% CI 17%-69%) | 100.0% (10/10, 95% CI 72%-100%) |
| other | 72.2% (13/18, 95% CI 49%-88%) | 77.8% (14/18, 95% CI 55%-91%) |
| promotions | 70.0% (7/10, 95% CI 40%-89%) | 90.0% (9/10, 95% CI 60%-98%) |

By difficulty

| difficulty | Both labels right | Category right |
|---|---|---|
| easy | 73.3% (22/30, 95% CI 56%-86%) | 93.3% (28/30, 95% CI 79%-98%) |
| hard | 85.0% (17/20, 95% CI 64%-95%) | 90.0% (18/20, 95% CI 70%-97%) |
| medium | 53.3% (16/30, 95% CI 36%-70%) | 93.3% (28/30, 95% CI 79%-98%) |

By language

| language | Both labels right | Category right |
|---|---|---|
| en | 69.1% (47/68, 95% CI 57%-79%) | 91.2% (62/68, 95% CI 82%-96%) |
| zh | 66.7% (8/12, 95% CI 39%-86%) | 100.0% (12/12, 95% CI 76%-100%) |

## Deadlines

Answer key: 39 required deadlines, written 41 times in 39 mails; 50 times that are not student work, 6 optional dates, 2 due dates inside receipts.
System: 86 tasks, 78 open (62 with a date, 16 without), 8 closed. Analysis failed on 0 mail(s).

| Measure | System | Regex baseline |
|---|---|---|
| Recall, each mail on its own (stated date extracted) | 97.6% (40/41, 95% CI 87%-100%) | 56.1% (23/41, 95% CI 41%-70%) |
| Recall, unique deadlines with their final date | 97.4% (38/39, 95% CI 87%-100%) | 56.4% (22/39, 95% CI 41%-71%) |
| Precision, each mail on its own | 61.3% (38/62, 95% CI 49%-72%) | 59.0% (23/39, 95% CI 43%-73%) |
| Precision of the task list (duplicates and outdated dates count as wrong) | 58.1% (36/62, 95% CI 46%-70%) | 56.4% (22/39, 95% CI 41%-71%) |

- Second reading (added after the first results): if 'attend <event>' tasks were accepted as tasks (17 of them), precision would be 88.7% (55/62, 95% CI 78%-94%) per mail and 85.5% (53/62, 95% CI 75%-92%) for the task list.
- Missed deadlines by reason: {'date_missing': 1}
- Open tasks by outcome: {'stale': 2, 'correct': 38, 'undated_spurious': 8, 'optional_promoted': 6, 'non_task_promoted': 20, 'undated_extra': 1, 'duplicate_in_mail': 2, 'date_missing': 1}
- Closed tasks by outcome: {'not_open': 8}
- Times that are not student work turned into open tasks: 20/50
  - event_time: 19/22
  - phishing_threat: 1/1
- Optional dates turned into open tasks: 6/6
- Receipts re-opened as work: 0/2
- Time of day on correctly dated tasks: {'time_as_expected': 40}
- Time zone on correctly dated tasks: {'stated_and_right': 3, 'none_stated_none_given': 37}

Recall (each mail on its own) by difficulty

| difficulty | Recall |
|---|---|
| easy | 100.0% (7/7, 95% CI 65%-100%) |
| hard | 100.0% (16/16, 95% CI 81%-100%) |
| medium | 94.4% (17/18, 95% CI 74%-99%) |

Recall (each mail on its own) by language

| language | Recall |
|---|---|
| en | 97.2% (35/36, 95% CI 86%-100%) |
| zh | 100.0% (5/5, 95% CI 57%-100%) |

Recall (each mail on its own) by category

| category | Recall |
|---|---|
| academic | 100.0% (23/23, 95% CI 86%-100%) |
| career | 100.0% (6/6, 95% CI 61%-100%) |
| events | 100.0% (2/2, 95% CI 34%-100%) |
| other | 90.0% (9/10, 95% CI 60%-98%) |

Recall (each mail on its own) by tag

| tag | Recall |
|---|---|
| boundary | 100.0% (3/3, 95% CI 44%-100%) |
| later_updated | 100.0% (2/2, 95% CI 34%-100%) |
| multi_deadline | 100.0% (3/3, 95% CI 44%-100%) |
| needs_academic_calendar | 100.0% (1/1, 95% CI 21%-100%) |
| no_time | 94.7% (18/19, 95% CI 75%-99%) |
| relative_date | 100.0% (10/10, 95% CI 72%-100%) |
| repeat_mention | 100.0% (2/2, 95% CI 34%-100%) |
| response_deadline | 85.7% (6/7, 95% CI 49%-97%) |
| timezone | 100.0% (2/2, 95% CI 34%-100%) |
| two_dates | 100.0% (2/2, 95% CI 34%-100%) |
| update | 100.0% (1/1, 95% CI 21%-100%) |
| weekday_date_conflict | 100.0% (1/1, 95% CI 21%-100%) |

## Data minimisation

Addresses, links, phone numbers, codes and long IDs removed before storage: 96.2% (25/26, 95% CI 81%-99%).
Still present: [{'mail': 'synO01', 'kind': 'number or code'}]

## Every error

Triage (30):

- `synA09` expected ignore / academic, got action / academic - DAT5310 Assignment 1 grades have been released; log in to the course portal to view your score and feedback.
- `synA10` expected ignore / academic, got action / academic - Assignment 1 grades are out; if you believe there is a grading error, you may request a regrade by 21 October, and your score may go up or down.
- `synA12` expected reply / academic, got reply+action / academic - A teammate asks you to handle capstone data cleaning and reply by tomorrow evening.
- `synA15` expected ignore / academic, got action / academic - The STA5120 lecture tomorrow has moved to LT12 and runs from 14:00 to 16:00.
- `synA19` expected ignore / academic, got action / academic - The school invites students to voluntarily complete an anonymous mid-semester course feedback survey by 2026-10-25.
- `synA27` expected reply / academic, got reply+action / academic - Please report which dataset (A, B, or C) your project group chose by Wednesday.
- `synA30` expected ignore / academic, got action / academic - The consultation is confirmed for 16:30 on 29 October at the office.
- `synC01` expected ignore / career, got action / career - Northwind Consulting is hiring 2027 graduate Data Analysts; applications close on 2026-10-31.
- `synC02` expected reply / career, got reply+action / career - Harborlight Insurance invited you to a first-round video interview for the Data Analyst Intern role; reply with your availability for November 3–5 by October 30.
- `synC04` expected reply / career, got reply+action / career - They are happy to do a mock interview and ask you to choose a time.
- `synC10` expected reply / career, got reply+action / career - Received an online interview invitation for a data analyst internship and must reply to confirm by November 5.
- `synC12` expected ignore / career, got ignore / academic - The transcript has been received and filed; no action is needed for now.
- `synE02` expected ignore / events, got reply+action / events - You are invited to the Capstone sync on October 16; please confirm whether you will attend.
- `synE03` expected ignore / events, got action / events - The Lakeside Hackathon takes place on 7–8 November 2026; interested participants must register their team by 30 October.
- `synE07` expected ignore / events, got action / events - The autumn welcome gathering is on October 24 at 15:00; interested students should complete the registration form by Thursday.
- `synE08` expected ignore / events, got reply+action / events - The Capstone sync has been rescheduled to 2026-10-19, and you are asked to respond whether you will attend.
- `synE09` expected reply / events, got reply+action / events - Invited to join the alumni networking night panel on 18 November; reply by 6 November.
- `synE10` expected ignore / events, got action / events - The Intro to dbt webinar starts today at 20:00 Singapore time.
- `synP01` expected ignore / promotions, got action / promotions - Limited-time discount on the SkillForge annual plan ends at midnight on 2026-10-18.
- `synP03` expected ignore / promotions, got ignore / academic - The machine learning newsletter covers evaluation-set leakage, feature stores, and gradient-boosted tree calibration.
- `synP05` expected ignore / promotions, got action / promotions - Meridian Bank promotes a student card; apply by 2026-11-30, and cashback is conditional on spending.
- `synP06` expected ignore / promotions, got action / promotions - DataPro says the scholarship discount expires tonight and asks you to confirm your seat to keep it.
- `synO02` expected ignore / other, got action / other - Lakeside detected a new sign-in; reset your password immediately if it wasn't you.
- `synO07` expected reply / other, got reply+action / other - Choose an air-con repair date by Friday; someone must be in the room during the repair.
- `synO08` expected action / other, got action / academic - The Student's Pass expires on 30 November 2026; apply for renewal and upload the acknowledgement by 16 November.
- `synO09` expected ignore / other, got ignore / academic - The course portal will be under maintenance on October 25 from 02:00 to 06:00; submissions will be unavailable, and no deadlines fall during this window.
- `synO10` expected ignore / other, got action / other - The email requests a username and password under threat of mailbox deactivation and appears to be phishing; do not reply with credentials.
- `synO13` expected reply / other, got reply+action / events - Reply YES by October 23 to keep the October 26 Health Centre appointment.
- `synO14` expected action / other, got action / events - Please clear the area around the air-conditioning unit and window before the October 29 inspection.
- `synO16` expected ignore / other, got action / other - An online payment of CNY 268 was made from the account ending in 1234; contact customer service if it was not you.

Deadlines (39):

- `synO13` date_missing: expected ['2026-10-23'] [None] ("by Friday, 23 October"); got None None "确认健康中心预约" [pending]
- `synA01` stale: task "Submit Assignment 2" 2026-10-30 23:59 from deadline "due on Friday, 30 October 2026 at 23:59 (SGT)"
- `synA02` stale: task "Submit Assignment 2" 2026-10-30 23:59 from deadline "due this Friday at 23:59"
- `synA09` undated_spurious: task "View DAT5310 Assignment 1 grade and feedback" None None
- `synA10` optional_promoted: task "Request a regrade for Assignment 1" 2026-10-21 None from optional "submit a regrade request through the portal by 21 October"
- `synA15` non_task_promoted: task "STA5120 lecture (venue changed to LT12)" 2026-10-21 14:00 from non_task/event_time "Wednesday, 21 October, 14:00-16:00"
- `synA18` non_task_promoted: task "Reply to the online meeting invitation" 2026-10-20 20:00 from non_task/event_time "明晚8点"
- `synA19` optional_promoted: task "Complete the mid-semester course feedback survey" 2026-10-25 None from optional "The survey closes on 25 October"
- `synA20` non_task_promoted: task "Office hours this week" 2026-11-05 None from non_task/event_time "Thursday 3-4 pm"
- `synA30` non_task_promoted: task "Attend the consultation" 2026-10-29 16:30 from non_task/event_time "Thursday, 29 October, 4:30 pm"
- `synC01` optional_promoted: task "Apply for Northwind Consulting's 2027 graduate Data Analyst role" 2026-10-31 None from optional "Applications close on 31 October 2026"
- `synC04` non_task_promoted: task "Mock interview (time option 1)" None None from non_task/event_time "Thursday 22 October at 7 pm"
- `synC04` non_task_promoted: task "Mock interview (time option 2)" None None from non_task/event_time "Saturday 24 October at 10 am"
- `synC08` optional_promoted: task "Apply for the Business Intelligence Intern position" None None from optional "apply by 20 November"
- `synC08` undated_spurious: task "Apply for the Data Science Intern position" None None
- `synC08` undated_spurious: task "Apply for the Analytics Intern position" None None
- `synC08` undated_spurious: task "Apply for the Junior Data Engineer position" None None
- `synC08` undated_spurious: task "Apply for the part-time Research Assistant position" None None
- `synC09` non_task_promoted: task "CV review appointment" 2026-10-27 14:00 from non_task/event_time "Tuesday, 27 October at 2 pm"
- `synC10` non_task_promoted: task "Attend the online interview for the data analyst internship" 2026-11-10 14:00 from non_task/event_time "11月10日下午2点"
- `synE01` non_task_promoted: task "Causal ML in Practice seminar" 2026-10-22 16:00 from non_task/event_time "Thursday, 22 October, 4:00-5:00 pm"
- `synE02` non_task_promoted: task "Capstone sync" 2026-10-16 15:00 from non_task/event_time "Fri 16 Oct 2026 3pm - 4pm Singapore Standard Time"
- `synE03` optional_promoted: task "Register a hackathon team" 2026-10-30 None from optional "Register your team by 30 October"
- `synE06` non_task_promoted: task "Coffee chat with alumni" 2026-10-21 17:00 from non_task/event_time "Wednesday, 21 October, 5 pm"
- `synE06` non_task_promoted: task "Deepavali celebration" 2026-11-06 18:00 from non_task/event_time "Friday, 6 November, 6 pm"
- `synE06` undated_spurious: task "Badminton social" None None
- `synE07` non_task_promoted: task "Attend the autumn welcome gathering" 2026-10-24 15:00 from non_task/event_time "本周六（10月24日）下午3点"
- `synE07` optional_promoted: task "Complete the welcome gathering registration form" 2026-10-22 None from optional "请在周四前填写报名表"
- `synE08` non_task_promoted: task "Attend Capstone sync" 2026-10-19 10:00 from non_task/event_time "Mon 19 Oct 2026 10am - 11am Singapore Standard Time"
- `synE09` non_task_promoted: task "Share a student's perspective at the alumni networking night" 2026-11-18 None from non_task/event_time "on 18 November"
- `synE10` non_task_promoted: task "Attend the Intro to dbt webinar" 2026-11-03 20:00 from non_task/event_time "today, 8:00 PM SGT"
- `synO02` undated_spurious: task "Reset your password immediately if you do not recognize this sign-in" None None
- `synO07` non_task_promoted: task "Air-con repair: 27 October, 14:00–16:00" 2026-10-27 None from non_task/event_time "Tuesday 27 October or Wednesday 28 October, between 2 and 4 pm"
- `synO07` duplicate_in_mail: task "Air-con repair: 28 October, 14:00–16:00" 2026-10-28 None from non_task/event_time "Tuesday 27 October or Wednesday 28 October, between 2 and 4 pm"
- `synO08` duplicate_in_mail: task "Upload the renewal application acknowledgement" 2026-11-16 None from deadline "by 16 November 2026"
- `synO09` non_task_promoted: task "Scheduled course portal maintenance" 2026-10-25 02:00 from non_task/event_time "Sunday, 25 October, from 02:00 to 06:00"
- `synO10` non_task_promoted: task "Reply to the email with your username and password" None None from non_task/phishing_threat "deactivated on 20 October"
- `synO13` non_task_promoted: task "Attend the Health Centre appointment" 2026-10-26 09:40 from non_task/event_time "Monday, 26 October 2026 at 9:40 AM"
- `synO16` undated_spurious: task "Contact the bank's customer service if this was not you" None None
