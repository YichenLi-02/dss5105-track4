# Mail evaluation - mail_synthetic_run2

Answer key: mail_eval_v1, 80 mails. Label status: **checked by a person**.

Run: model `gpt-6-luna`, prompt `p00-p02.v1`, schema `mail_analysis.v6`, code `14f3950`, 2026-11-10T10:38:42+00:00. Model time 611.2 s for 80 mails; tokens in 60490, out 49966. Outbound requests refused: 0.

## Triage

| Label | Precision | Recall | F1 | TP | FP | FN | TN | Keyword baseline F1 |
|---|---|---|---|---|---|---|---|---|
| needs_reply | 86.7% (13/15, 95% CI 62%-96%) | 100.0% (13/13, 95% CI 77%-100%) | 0.929 | 13 | 2 | 0 | 65 | 0.828 |
| needs_action | 56.1% (32/57, 95% CI 43%-68%) | 100.0% (32/32, 95% CI 89%-100%) | 0.719 | 32 | 25 | 0 | 23 | 0.708 |

- Both labels right: 68.8% (55/80, 95% CI 58%-78%); keyword baseline 73.8% (59/80, 95% CI 63%-82%).
- Mails that need nothing and were left alone: 57.5% (23/40, 95% CI 42%-72%).
- Mails that need attention but were marked ignore: 0.0% (0/40, 95% CI 0%-9%).
- Category: 93.8% (75/80, 95% CI 86%-97%); always guessing the largest category 37.5% (30/80, 95% CI 28%-48%).
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
| **academic** | 29 | 0 | 1 | 0 | 0 | 0 |
| **career** | 1 | 11 | 0 | 0 | 0 | 0 |
| **events** | 0 | 0 | 10 | 0 | 0 | 0 |
| **promotions** | 0 | 0 | 0 | 10 | 0 | 0 |
| **other** | 3 | 0 | 0 | 0 | 15 | 0 |

By category

| category | Both labels right | Category right |
|---|---|---|
| academic | 80.0% (24/30, 95% CI 63%-90%) | 96.7% (29/30, 95% CI 83%-99%) |
| career | 58.3% (7/12, 95% CI 32%-81%) | 91.7% (11/12, 95% CI 65%-98%) |
| events | 40.0% (4/10, 95% CI 17%-69%) | 100.0% (10/10, 95% CI 72%-100%) |
| other | 72.2% (13/18, 95% CI 49%-88%) | 83.3% (15/18, 95% CI 61%-94%) |
| promotions | 70.0% (7/10, 95% CI 40%-89%) | 100.0% (10/10, 95% CI 72%-100%) |

By difficulty

| difficulty | Both labels right | Category right |
|---|---|---|
| easy | 73.3% (22/30, 95% CI 56%-86%) | 90.0% (27/30, 95% CI 74%-96%) |
| hard | 85.0% (17/20, 95% CI 64%-95%) | 100.0% (20/20, 95% CI 84%-100%) |
| medium | 53.3% (16/30, 95% CI 36%-70%) | 93.3% (28/30, 95% CI 79%-98%) |

By language

| language | Both labels right | Category right |
|---|---|---|
| en | 69.1% (47/68, 95% CI 57%-79%) | 92.6% (63/68, 95% CI 84%-97%) |
| zh | 66.7% (8/12, 95% CI 39%-86%) | 100.0% (12/12, 95% CI 76%-100%) |

## Deadlines

Answer key: 39 required deadlines, written 41 times in 39 mails; 50 times that are not student work, 6 optional dates, 2 due dates inside receipts.
System: 86 tasks, 78 open (65 with a date, 13 without), 8 closed. Analysis failed on 0 mail(s).

| Measure | System | Regex baseline |
|---|---|---|
| Recall, each mail on its own (stated date extracted) | 92.7% (38/41, 95% CI 81%-98%) | 56.1% (23/41, 95% CI 41%-70%) |
| Recall, unique deadlines with their final date | 92.3% (36/39, 95% CI 80%-97%) | 56.4% (22/39, 95% CI 41%-71%) |
| Precision, each mail on its own | 56.9% (37/65, 95% CI 45%-68%) | 59.0% (23/39, 95% CI 43%-73%) |
| Precision of the task list (duplicates and outdated dates count as wrong) | 53.8% (35/65, 95% CI 42%-65%) | 56.4% (22/39, 95% CI 41%-71%) |

- Second reading (added after the first results): if 'attend <event>' tasks were accepted as tasks (20 of them), precision would be 87.7% (57/65, 95% CI 78%-94%) per mail and 84.6% (55/65, 95% CI 74%-91%) for the task list.
- Missed deadlines by reason: {'wrong_date': 1, 'date_missing': 1, 'missed': 1}
- Open tasks by outcome: {'stale': 2, 'correct': 36, 'wrong_date': 1, 'undated_spurious': 7, 'optional_promoted': 6, 'non_task_promoted': 23, 'date_missing': 1, 'duplicate_in_mail': 1, 'undated_extra': 1}
- Closed tasks by outcome: {'not_open': 8}
- Times that are not student work turned into open tasks: 23/50
  - event_time: 21/22
  - phishing_threat: 1/1
  - security_timestamp: 1/1
- Optional dates turned into open tasks: 6/6
- Receipts re-opened as work: 0/2
- Time of day on correctly dated tasks: {'time_as_expected': 38}
- Time zone on correctly dated tasks: {'stated_and_right': 3, 'none_stated_none_given': 35}

Recall (each mail on its own) by difficulty

| difficulty | Recall |
|---|---|
| easy | 100.0% (7/7, 95% CI 65%-100%) |
| hard | 93.8% (15/16, 95% CI 72%-99%) |
| medium | 88.9% (16/18, 95% CI 67%-97%) |

Recall (each mail on its own) by language

| language | Recall |
|---|---|
| en | 91.7% (33/36, 95% CI 78%-97%) |
| zh | 100.0% (5/5, 95% CI 57%-100%) |

Recall (each mail on its own) by category

| category | Recall |
|---|---|
| academic | 95.7% (22/23, 95% CI 79%-99%) |
| career | 100.0% (6/6, 95% CI 61%-100%) |
| events | 100.0% (2/2, 95% CI 34%-100%) |
| other | 80.0% (8/10, 95% CI 49%-94%) |

Recall (each mail on its own) by tag

| tag | Recall |
|---|---|
| boundary | 100.0% (3/3, 95% CI 44%-100%) |
| later_updated | 100.0% (2/2, 95% CI 34%-100%) |
| multi_deadline | 100.0% (3/3, 95% CI 44%-100%) |
| needs_academic_calendar | 100.0% (1/1, 95% CI 21%-100%) |
| no_time | 89.5% (17/19, 95% CI 69%-97%) |
| relative_date | 90.0% (9/10, 95% CI 60%-98%) |
| repeat_mention | 100.0% (2/2, 95% CI 34%-100%) |
| response_deadline | 71.4% (5/7, 95% CI 36%-92%) |
| timezone | 100.0% (2/2, 95% CI 34%-100%) |
| two_dates | 100.0% (2/2, 95% CI 34%-100%) |
| update | 100.0% (1/1, 95% CI 21%-100%) |
| weekday_date_conflict | 0.0% (0/1, 95% CI 0%-79%) |

## Data minimisation

Addresses, links, phone numbers, codes and long IDs removed before storage: 96.2% (25/26, 95% CI 81%-99%).
Still present: [{'mail': 'synO01', 'kind': 'number or code'}]

## Every error

Triage (29):

- `synA09` expected ignore / academic, got action / academic - DAT5310 Assignment 1 grades are available; log in to the course portal to view your score and feedback.
- `synA10` expected ignore / academic, got action / academic - DAT5310 Assignment 1 grades are out; if you believe there was a grading error, you may request a regrade by October 21.
- `synA12` expected reply / academic, got reply+action / academic - Please reply whether you can handle capstone data cleaning by tomorrow evening.
- `synA19` expected ignore / academic, got action / academic - Please voluntarily complete the anonymous mid-semester course feedback survey by October 25.
- `synA27` expected reply / academic, got reply+action / academic - Please tell the project group which dataset you chose by Wednesday.
- `synA30` expected ignore / academic, got action / events - The consultation is confirmed for October 29 at 16:30 in the office; no preparation is needed.
- `synC01` expected ignore / career, got action / career - Northwind Consulting is hiring 2027 graduate Data Analysts; applications close on 2026-10-31.
- `synC02` expected reply / career, got reply+action / career - Harborlight Insurance invites you to a first-round video interview for the Data Analyst Intern role; reply with your availability for November 3–5 by October 30.
- `synC04` expected reply / career, got reply+action / career - Daniel proposes a mock interview over video and asks whether Thursday or Saturday works better.
- `synC08` expected ignore / career, got action / career - Received five new job recommendations, one with an application deadline of November 20 (year not specified).
- `synC10` expected reply / career, got reply+action / career - Xinglan Data invites you to an online interview for the data analyst internship; reply to confirm by November 5.
- `synC12` expected ignore / career, got ignore / academic - The transcript was received and added to the file; no further action is needed for now.
- `synE02` expected ignore / events, got reply+action / events - You are invited to the Capstone sync on October 16; please respond whether you will attend.
- `synE03` expected ignore / events, got action / events - The Lakeside Hackathon takes place November 7–8; register by October 30.
- `synE07` expected ignore / events, got action / events - The fall welcome party is on October 24; interested students should fill out the registration form by Thursday.
- `synE08` expected ignore / events, got reply+action / events - Capstone sync was updated to 2026-10-19, and the invitation provides response options.
- `synE09` expected reply / events, got reply+action / events - Please reply by 6 November whether you can join the alumni networking night panel on 18 November.
- `synE10` expected ignore / events, got action / events - The Intro to dbt live webinar starts today at 20:00 Singapore time.
- `synP01` expected ignore / promotions, got action / promotions - SkillForge advertises a limited-time annual plan offer, with 40% off ending at midnight on 2026-10-18.
- `synP05` expected ignore / promotions, got action / promotions - Meridian Bank promotes a student credit card with S$200 cashback for applying and meeting the spending condition.
- `synP06` expected ignore / promotions, got action / promotions - The DataPro Data Science Bootcamp scholarship discount expires tonight; confirm your seat to lock it in.
- `synO02` expected ignore / other, got action / other - Lakeside detected a new sign-in; if it was not you, reset your password immediately.
- `synO04` expected ignore / other, got ignore / academic - Tuition instalment 2 payment received; no further action is required.
- `synO06` expected action / other, got action / academic - Renew or return the library item by 2026-10-28.
- `synO07` expected reply / other, got reply+action / other - Choose and reply with an air-con repair date by Friday; someone must be in the room during the repair.
- `synO09` expected ignore / other, got ignore / academic - The course portal will undergo maintenance on October 25 from 02:00 to 06:00, during which submissions will be unavailable.
- `synO10` expected ignore / other, got action / other - The email claims the mailbox will be deactivated and asks for a username and password; this request is highly suspicious.
- `synO13` expected reply / other, got reply+action / other - Reply YES by October 23 to keep the October 26 Health Centre appointment.
- `synO16` expected ignore / other, got action / other - The account received a notice of a CNY 268.00 online payment; call customer service if it was not made by you.

Deadlines (43):

- `synA06` wrong_date: expected [None] ['18:00', None] ("due Thursday, 23 October at 6 pm"); got 2026-10-23 18:00 "提交实验 3 报告和 docker-compose 文件" [pending]
- `synO07` date_missing: expected ['2026-10-23'] [None] ("Please let me know by Friday"); got None None "回复并选择空调维修日期" [pending]
- `synO13` missed: expected ['2026-10-23'] [None] ("by Friday, 23 October")
- `synA01` stale: task "Submit Assignment 2" 2026-10-30 23:59 from deadline "due on Friday, 30 October 2026 at 23:59 (SGT)"
- `synA02` stale: task "Submit Assignment 2" 2026-10-30 23:59 from deadline "due this Friday at 23:59"
- `synA06` wrong_date: task "Submit the Lab 3 report and docker-compose file" 2026-10-23 18:00 from deadline "due Thursday, 23 October at 6 pm"
- `synA09` undated_spurious: task "View score and feedback" None None
- `synA10` optional_promoted: task "Submit an Assignment 1 regrade request" 2026-10-21 None from optional "submit a regrade request through the portal by 21 October"
- `synA15` non_task_promoted: task "STA5120 lecture (venue change)" 2026-10-21 None from non_task/event_time "Wednesday, 21 October, 14:00-16:00"
- `synA18` non_task_promoted: task "Attend the online task-allocation meeting" 2026-10-20 20:00 from non_task/event_time "明晚8点"
- `synA19` optional_promoted: task "Complete the mid-semester feedback survey" 2026-10-25 None from optional "The survey closes on 25 October"
- `synA20` non_task_promoted: task "Office hours this week" 2026-11-05 15:00 from non_task/event_time "Thursday 3-4 pm"
- `synA30` non_task_promoted: task "Attend consultation" 2026-10-29 16:30 from non_task/event_time "Thursday, 29 October, 4:30 pm"
- `synC01` optional_promoted: task "Apply for the Northwind Consulting Data Analyst role" 2026-10-31 None from optional "Applications close on 31 October 2026"
- `synC02` non_task_promoted: task "Attend the first-round video interview" None None from non_task/event_time "availability on 3-5 November"
- `synC04` non_task_promoted: task "Confirm the mock interview time (Thursday option)" 2026-10-22 19:00 from non_task/event_time "Thursday 22 October at 7 pm"
- `synC04` non_task_promoted: task "Confirm the mock interview time (Saturday option)" 2026-10-24 10:00 from non_task/event_time "Saturday 24 October at 10 am"
- `synC08` optional_promoted: task "Business Intelligence Intern" None None from optional "apply by 20 November"
- `synC08` undated_spurious: task "Data Science Intern" None None
- `synC08` undated_spurious: task "Analytics Intern" None None
- `synC08` undated_spurious: task "Junior Data Engineer" None None
- `synC08` undated_spurious: task "Research Assistant (part-time)" None None
- `synC09` non_task_promoted: task "CV review appointment" 2026-10-27 14:00 from non_task/event_time "Tuesday, 27 October at 2 pm"
- `synC10` non_task_promoted: task "Attend the online interview for the data analyst internship" 2026-11-10 14:00 from non_task/event_time "11月10日下午2点"
- `synE01` non_task_promoted: task "Causal ML in Practice" 2026-10-22 None from non_task/event_time "Thursday, 22 October, 4:00-5:00 pm"
- `synE02` non_task_promoted: task "Capstone sync" 2026-10-16 15:00 from non_task/event_time "Fri 16 Oct 2026 3pm - 4pm Singapore Standard Time"
- `synE03` non_task_promoted: task "Attend the Lakeside Hackathon" 2026-11-07 None from non_task/event_time "on 7-8 November"
- `synE03` optional_promoted: task "Register for the Lakeside Hackathon" 2026-10-30 None from optional "Register your team by 30 October"
- `synE04` non_task_promoted: task "Attend the Python for Data Pipelines workshop" 2026-10-31 09:00 from non_task/event_time "Saturday, 31 October, 9 am - 1 pm"
- `synE06` non_task_promoted: task "Coffee chat with alumni" 2026-10-21 17:00 from non_task/event_time "Wednesday, 21 October, 5 pm"
- `synE06` non_task_promoted: task "Deepavali celebration" 2026-11-06 18:00 from non_task/event_time "Friday, 6 November, 6 pm"
- `synE06` undated_spurious: task "Badminton social" None None
- `synE07` optional_promoted: task "Fill out the welcome party registration form" 2026-10-22 None from optional "请在周四前填写报名表"
- `synE07` non_task_promoted: task "Attend the fall welcome party" 2026-10-24 15:00 from non_task/event_time "本周六（10月24日）下午3点"
- `synE08` non_task_promoted: task "Capstone sync" 2026-10-19 10:00 from non_task/event_time "Mon 19 Oct 2026 10am - 11am Singapore Standard Time"
- `synE09` non_task_promoted: task "Join the alumni networking night panel" 2026-11-18 None from non_task/event_time "on 18 November"
- `synE10` non_task_promoted: task "Attend the Intro to dbt live webinar" 2026-11-03 20:00 from non_task/event_time "today, 8:00 PM SGT"
- `synO02` non_task_promoted: task "If the sign-in was not yours, reset your password immediately" 2026-10-17 22:14 from non_task/security_timestamp "17 October 2026, 22:14 SGT"
- `synO07` non_task_promoted: task "Air-con repair (Tuesday option)" 2026-10-27 None from non_task/event_time "Tuesday 27 October or Wednesday 28 October, between 2 and 4 pm"
- `synO07` duplicate_in_mail: task "Air-con repair (Wednesday option)" 2026-10-28 None from non_task/event_time "Tuesday 27 October or Wednesday 28 October, between 2 and 4 pm"
- `synO10` non_task_promoted: task "Reply by email with the username and password" None None from non_task/phishing_threat "deactivated on 20 October"
- `synO13` non_task_promoted: task "Confirm University Health Centre appointment" 2026-10-26 09:40 from non_task/event_time "Monday, 26 October 2026 at 9:40 AM"
- `synO16` undated_spurious: task "Call customer service if you did not make this transaction" None None
