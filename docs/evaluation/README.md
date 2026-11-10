# Evaluation

How well the assistant works and where it fails. Results and failure analysis: [RESULTS.md](RESULTS.md).

## What is here

| Path | What it is |
|---|---|
| `RESULTS.md` | The written evaluation: measures, how the sets were built, results by category, 15 failure cases, next steps |
| `results/mail_summary.md` | Triage and deadline numbers for every run side by side |
| `results/mail_<set>_run<n>.report.md` | One run in full: tables, confusion matrices and every single error |
| `results/mail_<set>_run<n>.predictions.json` | Raw output of that run (labels, model candidates, tasks, stored text) |
| `results/safety.md`, `safety_run<n>.json` | Safety red-team: 20 specifications, three runs, worst outcome counts |
| `results/planner.md` | Planner evaluation report |
| `../../data/synthetic/mail_eval_v1/` | The 80 fictional mails, their answer key and the labelling rules |
| `../../src/backend/evaluation/` | `mail_eval.py`, `safety_eval.py`, `planner_eval.py` |
| `../../src/backend/tests/test_mail_eval_scoring.py` | Tests of the scorer itself |

## Reproduce

From the repository root, after the normal setup in the main README. The mail and safety runs need the model
settings in `.env` and spend tokens (about 1,400 per mail; the whole evaluation used roughly half a million).

```bash
src/backend/.venv/bin/python data/synthetic/mail_eval_v1/build_dataset.py --check   # dataset matches its manifest
src/backend/.venv/bin/python scripts/eval-mail.py smoke                              # 2 throwaway mails, checks the plumbing
src/backend/.venv/bin/python scripts/eval-mail.py run --set synthetic --run 1        # repeat with --run 2, --run 3
src/backend/.venv/bin/python scripts/eval-mail.py run --set samples --run 1
src/backend/.venv/bin/python scripts/eval-mail.py score                              # no model: scores every saved run
src/backend/.venv/bin/python scripts/eval-safety.py --run 1                          # repeat with --run 2, --run 3
src/backend/.venv/bin/python scripts/eval-planner.py                                 # no model
```

Model output varies, so a new run will not reproduce the numbers exactly; the saved predictions do
(`eval-mail.py score` and `eval-safety.py --merge` recompute everything from them).

## What a run touches

Each run creates an empty database under `local-data/eval/` and never opens the app's own data. Login tokens are
kept in memory, not in the system keychain. The app runs in demo mode with external writes off. All outbound
requests go through a transport that serves the synthetic mailbox as a read-only Gmail API, lets the configured
model endpoint through, and refuses and records everything else. In the safety run, live mode is switched on only
with every mail and calendar provider replaced by a recorder.

## Rules we kept

- The answer key was frozen (`MANIFEST.json`) before the first run and is never read by the app.
- No prompt, rule or threshold of the app was changed for or during the evaluation.
- Checks are not loosened after seeing results. The three changes that were made afterwards (one scorer fix, one
  corrected safety scenario, one added second reading) are listed in `RESULTS.md` section 2.
- If the app is changed in response to these results, this mail set becomes development data and a new set is needed.

## Time-saved pilot (needs people)

```bash
src/backend/.venv/bin/python scripts/time-pilot.py start --participant 1    # about 15 minutes, in a terminal
src/backend/.venv/bin/python scripts/time-pilot.py summary --mails-per-week 120
```

Each participant handles 15 mails by hand and 15 with the assistant's saved output shown first, answering the same
three questions each time (reply needed, action needed, deadline dates). Odd-numbered participants do block A by
hand and block B assisted; even-numbered the reverse, starting with the assisted block. The two blocks have the same
category mix. Time with the assistant includes checking and correcting it. Report the result as a pilot with the
number of participants, state the weekly mail volume you assume, and do not extend it to planning time, which is
not measured.

## Still to do by people

1. Two team members check the synthetic answer key and the 40 sample labels; record agreement; re-score.
2. Collect and label a fresh real-mail hold-out.
3. Run the time pilot.
4. Check the expected values of the 27 fixed planner scenarios.
