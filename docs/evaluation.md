# Evaluation protocol

Status: proposed protocol; no measurements have been collected.

The course gives time saved against manual completion as an example for Track 4. An equally rigorous alternative is allowed when stated in the Sprint 2 validation plan. The course requires at least 10 individually analysed failure cases.

## Proposed measurements

- Triage: per-category precision/recall and confusion matrix.
- Deadlines: task and date/time correctness against independently checked annotations.
- Planning: deadline violations, availability conflicts and user correction rate.
- Productivity: task completion time manually versus assisted, including review/correction time; report quality alongside speed.

## Dataset and comparison

Use separate development and held-out sets. Include explicit dates, relative dates, missing time zones, conflicting updates, duplicate threads, messages with no action, and misleading instructions inside messages. Treat message contents as data, not authority to perform external actions.

Before implementation tuning, agree on sample size, category coverage, annotation rubric and success thresholds. Do not imply synthetic-only results generalise to real inboxes.

Use comparable manual and assisted task sets, counterbalance order where feasible, and record participant count, task count and timing method. Do not extrapolate weekly hours saved without stating workload assumptions.

## Failure log

Record at least 10 actual cases individually; do not fabricate failures to fill the report.

| Case ID | Category | Expected | Actual | Root cause | Impact | Mitigation |
| --- | --- | --- | --- | --- | --- | --- |

Final report: metrics and rationale; dataset construction and bias; overall and category results; individual failures; limitations; what to measure with more time. Disclose any evaluation data used during development and report held-out results separately.
