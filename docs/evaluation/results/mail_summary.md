# Mail evaluation - all runs

## samples

Runs: mail_samples_run1. Labels: NOT verified - annotation status in the files: {'AI_assisted_proposal_pending_user_review': 40}; treat every number as provisional.

| Measure | Mean | Min | Max |
|---|---|---|---|
| needs_reply_f1 | 0.909 | 0.909 | 0.909 |
| needs_action_f1 | 0.864 | 0.864 | 0.864 |
| exact_match | 0.8 | 0.8 | 0.8 |
| category_accuracy | 0.775 | 0.775 | 0.775 |
| deadline_recall_per_mail | 0.952 | 0.952 | 0.952 |
| deadline_recall_unique | 1.0 | 1.0 | 1.0 |
| deadline_precision_per_mail | 0.72 | 0.72 | 0.72 |
| deadline_precision_task_list | 0.44 | 0.44 | 0.44 |
| deadline_precision_task_list_if_event_tasks_accepted | 0.48 | 0.48 | 0.48 |
| non_task_became_open_task | 2.0 | 2 | 2 |
| optional_became_open_task | 2.0 | 2 | 2 |
| open_tasks_with_date | 25.0 | 25 | 25 |
| needs_action_precision | 0.76 | 0.76 | 0.76 |
| needs_action_recall | 1.0 | 1.0 | 1.0 |
| needs_reply_precision | 0.833 | 0.833 | 0.833 |
| needs_reply_recall | 1.0 | 1.0 | 1.0 |
| ignored_correctly | 0.737 | 0.737 | 0.737 |
| needed_attention_but_ignored | 0.0 | 0.0 | 0.0 |
| baseline_exact_match | 0.65 | 0.65 | 0.65 |
| baseline_deadline_recall_per_mail | 0.238 | 0.238 | 0.238 |
| baseline_deadline_precision_per_mail | 0.417 | 0.417 | 0.417 |
| secrets_removed | None | None | None |
| seconds_per_mail | 9.62 | 9.62 | 9.62 |
| tokens_per_mail | 1660.0 | 1660 | 1660 |
| open_tasks | 42.0 | 42 | 42 |
| analysis_failed | 1.0 | 1 | 1 |

## synthetic

Runs: mail_synthetic_run1, mail_synthetic_run2, mail_synthetic_run3. Labels: correct by construction (written with each mail, frozen before the first run); not yet reviewed by a human.

| Measure | Mean | Min | Max |
|---|---|---|---|
| needs_reply_f1 | 0.916 | 0.889 | 0.929 |
| needs_action_f1 | 0.714 | 0.703 | 0.719 |
| exact_match | 0.675 | 0.65 | 0.688 |
| category_accuracy | 0.934 | 0.925 | 0.938 |
| deadline_recall_per_mail | 0.96 | 0.927 | 0.976 |
| deadline_recall_unique | 0.957 | 0.923 | 0.974 |
| deadline_precision_per_mail | 0.595 | 0.569 | 0.613 |
| deadline_precision_task_list | 0.563 | 0.538 | 0.581 |
| deadline_precision_task_list_if_event_tasks_accepted | 0.847 | 0.841 | 0.855 |
| non_task_became_open_task | 20.333 | 18 | 23 |
| optional_became_open_task | 6.0 | 6 | 6 |
| open_tasks_with_date | 63.333 | 62 | 65 |
| needs_action_precision | 0.555 | 0.542 | 0.561 |
| needs_action_recall | 1.0 | 1.0 | 1.0 |
| needs_reply_precision | 0.864 | 0.857 | 0.867 |
| needs_reply_recall | 0.974 | 0.923 | 1.0 |
| ignored_correctly | 0.558 | 0.525 | 0.575 |
| needed_attention_but_ignored | 0.0 | 0.0 | 0.0 |
| baseline_exact_match | 0.738 | 0.738 | 0.738 |
| baseline_deadline_recall_per_mail | 0.561 | 0.561 | 0.561 |
| baseline_deadline_precision_per_mail | 0.59 | 0.59 | 0.59 |
| secrets_removed | 0.962 | 0.962 | 0.962 |
| seconds_per_mail | 7.777 | 7.64 | 7.93 |
| tokens_per_mail | 1390.333 | 1381 | 1408 |
| open_tasks | 77.0 | 75 | 78 |
| analysis_failed | 0.0 | 0 | 0 |
