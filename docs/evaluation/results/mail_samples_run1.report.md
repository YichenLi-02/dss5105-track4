# Mail evaluation - mail_samples_run1

Answer key: selected_50 (de-identified real mail), 40 mails. Label status: **human reviewed**.

Run: model `gpt-6-luna`, prompt `p00-p02.v1`, schema `mail_analysis.v6`, code `14f3950`, 2026-11-10T10:34:55+00:00. Model time 384.7 s for 40 mails; tokens in 35584, out 30835. Outbound requests refused: 0.

## Triage

| Label | Precision | Recall | F1 | TP | FP | FN | TN | Keyword baseline F1 |
|---|---|---|---|---|---|---|---|---|
| needs_reply | 83.3% (5/6, 95% CI 44%-97%) | 100.0% (5/5, 95% CI 57%-100%) | 0.909 | 5 | 1 | 0 | 34 | 0.714 |
| needs_action | 80.0% (20/25, 95% CI 61%-91%) | 100.0% (20/20, 95% CI 84%-100%) | 0.889 | 20 | 5 | 0 | 15 | 0.732 |

- Both labels right: 82.5% (33/40, 95% CI 68%-91%); keyword baseline 65.0% (26/40, 95% CI 50%-78%).
- Mails that need nothing and were left alone: 77.8% (14/18, 95% CI 55%-91%).
- Mails that need attention but were marked ignore: 0.0% (0/22, 95% CI 0%-15%).
- Category: 77.5% (31/40, 95% CI 62%-88%); always guessing the largest category 57.5% (23/40, 95% CI 42%-72%).
- Mails with no model output: 1 ['M25']

Reply / action / ignore (rows: answer key, columns: system)

| | reply | action | reply+action | ignore | no output |
|---|---|---|---|---|---|
| **reply** | 0 | 0 | 2 | 0 | 0 |
| **action** | 0 | 16 | 1 | 0 | 0 |
| **reply+action** | 0 | 0 | 3 | 0 | 0 |
| **ignore** | 0 | 3 | 0 | 14 | 1 |

Category (rows: answer key, columns: system)

| | academic | career | events | promotions | other | no output |
|---|---|---|---|---|---|---|
| **academic** | 20 | 1 | 2 | 0 | 0 | 0 |
| **career** | 0 | 1 | 0 | 0 | 0 | 0 |
| **events** | 1 | 1 | 4 | 0 | 0 | 1 |
| **promotions** | 0 | 0 | 0 | 3 | 0 | 0 |
| **other** | 3 | 0 | 0 | 0 | 3 | 0 |

By category

| category | Both labels right | Category right |
|---|---|---|
| academic | 91.3% (21/23, 95% CI 73%-98%) | 87.0% (20/23, 95% CI 68%-96%) |
| career | 0.0% (0/1, 95% CI 0%-79%) | 100.0% (1/1, 95% CI 21%-100%) |
| events | 57.1% (4/7, 95% CI 25%-84%) | 57.1% (4/7, 95% CI 25%-84%) |
| other | 83.3% (5/6, 95% CI 44%-97%) | 50.0% (3/6, 95% CI 19%-81%) |
| promotions | 100.0% (3/3, 95% CI 44%-100%) | 100.0% (3/3, 95% CI 44%-100%) |

By language

| language | Both labels right | Category right |
|---|---|---|
| en | 82.5% (33/40, 95% CI 68%-91%) | 77.5% (31/40, 95% CI 62%-88%) |

By split

| split | Both labels right | Category right |
|---|---|---|
| dev | 89.5% (17/19, 95% CI 69%-97%) | 68.4% (13/19, 95% CI 46%-85%) |
| holdout | 76.2% (16/21, 95% CI 55%-89%) | 85.7% (18/21, 95% CI 65%-95%) |

## Deadlines

Answer key: 13 required deadlines, written 21 times in 14 mails; 5 times that are not student work, 2 optional dates, 2 due dates inside receipts.
System: 52 tasks, 42 open (25 with a date, 17 without), 10 closed. Analysis failed on 1 mail(s).

| Measure | System | Regex baseline |
|---|---|---|
| Recall, each mail on its own (stated date extracted) | 85.7% (18/21, 95% CI 65%-95%) | 23.8% (5/21, 95% CI 11%-45%) |
| Recall, unique deadlines with their final date | 100.0% (13/13, 95% CI 77%-100%) | 38.5% (5/13, 95% CI 18%-64%) |
| Precision, each mail on its own | 64.0% (16/25, 95% CI 44%-80%) | 41.7% (5/12, 95% CI 19%-68%) |
| Precision of the task list (duplicates and outdated dates count as wrong) | 44.0% (11/25, 95% CI 27%-63%) | 41.7% (5/12, 95% CI 19%-68%) |

- Second reading (added after the first results): if 'attend <event>' tasks were accepted as tasks (1 of them), precision would be 68.0% (17/25, 95% CI 48%-83%) per mail and 48.0% (12/25, 95% CI 30%-66%) for the task list.
- Missed deadlines by reason: {'wrong_date': 2, 'missed': 1}
- Open tasks by outcome: {'correct': 13, 'undated_extra': 9, 'duplicate_across_mails': 5, 'invented': 4, 'wrong_date': 2, 'non_task_promoted': 2, 'optional_promoted': 2, 'completed_reopened': 1, 'undated_spurious': 4}
- Closed tasks by outcome: {'not_open': 10}
- Times that are not student work turned into open tasks: 2/5
  - class_event: 1/1
  - security_token_lifetime: 1/1
- Optional dates turned into open tasks: 2/2
- Receipts re-opened as work: 1/2
- Time of day on correctly dated tasks: {'time_as_expected': 16, 'time_missing': 2}
- Time zone on correctly dated tasks: {'none_stated_none_given': 18}

Recall (each mail on its own) by language

| language | Recall |
|---|---|
| en | 85.7% (18/21, 95% CI 65%-95%) |

Recall (each mail on its own) by category

| category | Recall |
|---|---|
| academic | 84.2% (16/19, 95% CI 62%-94%) |
| other | 100.0% (2/2, 95% CI 34%-100%) |

Recall (each mail on its own) by split

| split | Recall |
|---|---|
| dev | 81.2% (13/16, 95% CI 57%-93%) |
| holdout | 100.0% (5/5, 95% CI 57%-100%) |

Recall (each mail on its own) by tag

| tag | Recall |
|---|---|
| 回复与行动并存 | 100.0% (1/1, 95% CI 21%-100%) |
| 日期冲突与延期 | 100.0% (2/2, 95% CI 34%-100%) |
| 相对日期与多任务 | 62.5% (5/8, 95% CI 31%-86%) |
| 考试时间窗与重复 | 100.0% (2/2, 95% CI 34%-100%) |
| 课程任务与截止日期 | 100.0% (5/5, 95% CI 57%-100%) |
| 财务行政行动 | 100.0% (2/2, 95% CI 34%-100%) |
| 需要回复 | 100.0% (1/1, 95% CI 21%-100%) |

## Every error

Triage (12):

- `M17` expected reply+action / academic, got reply+action / career - Please review the recommendation letter draft, revise your resume as suggested, and provide relevant experience information.
- `M18` expected reply / academic, got reply+action / events - Confirm by November 25, 2025 whether power is needed for equipment beyond laptops; otherwise, only laptop power will be assumed.
- `M19` expected reply+action / academic, got reply+action / events - Please confirm by November 25 whether the demo fits the default table space, or specify any additional space needed.
- `M20` expected reply / academic, got reply+action / academic - A teammate asks for feedback on the chat platform and the project contact email draft.
- `M24` expected action / events, got reply+action / career - Priya paused the internship progress meetings and asked you to message her on WhatsApp after completing the next steps and keep her updated.
- `M25` expected ignore / events, got no output / None [MODEL_EVIDENCE_INVALID]
- `M28` expected ignore / events, got action / academic - Marcus will join the meeting by phone, with his camera off and possibly distracted.
- `M31` expected ignore / career, got action / career - A Deloitte recruiter invites you to consider a Software Engineering Solutions Analyst role; no application deadline is specified.
- `M32` expected ignore / other, got action / other - The Microsoft OneDrive verification code is for verifying the account and accessing a shared document; it is valid for 15 minutes.
- `M37` expected action / other, got action / academic - A refund check was issued but not mailed; submit the form and choose a refund option within five days.
- `M38` expected ignore / other, got ignore / academic - Payment for the UBC Graduate Program Application Fee was completed successfully.
- `M39` expected ignore / other, got ignore / academic - The electronic transcript order was placed; delivery will wait for grades and degree posting.

Deadlines (23):

- `M04` wrong_date: expected ['2025-12-05', None] [None] ("both the final project and mini lab 5 are due today"); got 2025-12-06 None "提交期末项目" [pending]
- `M04` wrong_date: expected ['2025-12-05', None] [None] ("both the final project and mini lab 5 are due today"); got 2025-12-06 None "提交迷你实验 5" [pending]
- `M05` missed: expected ['2025-12-05'] [None] ("Quiz 13 and 14 will later be released and remain open until 12/05.")
- `M03` duplicate_across_mails: task "Submit the project results JSON file" 2025-12-06 23:59 from deadline "New deadline: Friday, Dec 6, 11:59 PM" (first seen in M01)
- `M03` invented: task "Receive 0.5% extra credit for submitting by the original deadline" 2025-12-05 None
- `M04` wrong_date: task "Submit the final project" 2025-12-06 None from deadline "both the final project and mini lab 5 are due today"
- `M04` wrong_date: task "Submit mini lab 5" 2025-12-06 None from deadline "both the final project and mini lab 5 are due today"
- `M05` duplicate_across_mails: task "Submit the final project" 2025-12-05 None from deadline "The final project (Due 12/05)" (first seen in M01)
- `M05` duplicate_across_mails: task "Complete Mini Lab 5" 2025-12-05 None from deadline "Mini Lab 5 (Due 12/05)" (first seen in M07)
- `M05` non_task_promoted: task "Attend the lecture on Zoom" 2025-12-03 None from non_task/class_event "The Wednesday (12/03) lecture will be held solely on Zoom"
- `M06` duplicate_across_mails: task "Complete Quiz 13" 2025-12-05 None from deadline "Both quizzes are due on 12/05." (first seen in M05)
- `M09` invented: task "Review the mock final exam" 2025-12-03 None
- `M11` duplicate_across_mails: task "Complete the CS 3120 Database Management final exam" 2025-12-08 None from deadline "Availability Window: December 8 (12:00 AM) – December 8 (11:59 PM)" (first seen in M10)
- `M12` optional_promoted: task "Submit a regrade request if you have concerns" 2025-12-11 23:59 from optional "if you have any concerns, submit a regrade request by 11:59 PM on December 11, 2025."
- `M14` completed_reopened: task "Resubmit Final Project Report (optional)" 2025-12-06 23:59 from completed "Due Date:
Dec 06, 2025 at 11:59:00 PM MST"
- `M26` undated_spurious: task "Lyrebird AI Team Meeting" None None
- `M27` undated_spurious: task "Lyrebird AI Team Meeting" None None
- `M28` invented: task "CS4860 Third Instructor Meeting: Lyrebird AI" 2025-11-21 13:00
- `M29` optional_promoted: task "Accept the Harbor offer" None None from optional "Monday, December 5, at 12 p.m. Mountain Standard Time"
- `M31` undated_spurious: task "Apply for the Software Engineering Solutions Analyst role" None None
- `M32` non_task_promoted: task "Verify the account to access the shared document" None None from non_task/security_token_lifetime "The code will only work for 15 minutes"
- `M35` invented: task "Lyrebird AI Team Meeting (Canceled)" 2025-09-12 10:00
- `M39` undated_spurious: task "Wait for grades or degree posting before processing and sending the transcript" None None
