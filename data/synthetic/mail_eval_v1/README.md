# Synthetic mailbox for the mail evaluation (`mail_eval_v1`)

80 fictional emails with an answer key, used to measure inbox triage and deadline extraction end to end.

**This is synthetic data.** Lakeside University, its course codes, the companies and the people do not exist; every
address uses the reserved `.example` domain. The mails were written with an AI assistant (Claude) from the quotas and
rules below; **every mail and its answer has since been checked by a person** (see the change log). Results on this set are an upper
bound: synthetic mail is cleaner than a real inbox.

| File | Purpose |
|---|---|
| `build_dataset.py` | Single source of truth. Dates and weekdays are computed, so they cannot drift from the key. |
| `messages.jsonl` | What the system receives (through a simulated Gmail API). |
| `labels.json` | The answer key. Read only by the scorer, never by the system. |
| `MANIFEST.json` | SHA-256 of both files, recorded before the first system run. |

`python data/synthetic/mail_eval_v1/build_dataset.py --check` verifies that the files still match the script.

## How bias was limited

1. **Quotas first.** Category, difficulty and language counts were fixed before any mail was written:
   academic 30, career 12, events 10, promotions 10, other 18; easy 30, medium 30, hard 20; English 68, Chinese 12.
2. **Labels before predictions.** The key was written with each mail and frozen (see `MANIFEST.json`) before the
   system saw any of them. No prompt, rule or label was changed after looking at results; if a label is later
   found to be wrong it is corrected only through a dated entry in the change log below, and both scores are kept.
3. **Existing definitions.** Labels follow the project's own definitions in `data/AI项目数据源_去隐私/prompts.md`
   (P01, P02), written weeks before this evaluation, not rules invented to fit the model.
4. **Hard cases on purpose.** A quarter of the set targets cases that the earlier real-mailbox test showed to be
   weak (notification mails, code lifetimes, receipts, repeated and updated deadlines) and cases the Track 4 brief
   names (relative dates, the same deadline in several mails, conflicts).
5. **Different author and judge.** The mails were written by one model family and are analysed by another
   (the app's configured OpenAI model), which removes "the model grading its own style" but not the general risk
   that machine-written mail is easier for a machine to read.

Known remaining bias: the author knew the system's weak points, one person-equivalent wrote all 80 mails, and
there are no long threads, HTML-heavy newsletters, attachments or forwarded chains. A real-mail check is reported
separately for that reason.

## Triage labels

Two independent yes/no labels per mail; `ignore` means both are no.

- **needs_reply**: the student is personally asked something and a reply is expected now (a question from a
  teammate or teacher, a recruiter asking for availability, "reply YES to keep your slot"). A generic RSVP button,
  a marketing "contact us" or an optional thank-you does not count.
- **needs_action**: there is real work or an obligation beyond replying (hand in coursework, sit a test, pay a fee,
  renew something, book a slot, confirm a seat the student already registered for). If the only thing to do is
  answer a question, it is `needs_reply` only.
- **Not required**: optional opportunities (job adverts, voluntary surveys, regrade windows, event sign-ups),
  receipts and confirmations, grade releases, security notices of the "if this was not you" kind, one-time codes,
  promotions however urgent they sound, and phishing.

`boundary` in a mail's tags marks the three cases where a reasonable annotator could disagree (job offer to sign,
confirming a registered seat, an invitation to speak).

## Category

`academic` courses, assessment, grades, teachers and classmates about coursework, exams ·
`career` recruiting, applications, interviews, offers, career services and mentoring (including career events) ·
`events` talks, club and social activities, calendar invitations ·
`promotions` marketing, discounts, upsell, newsletters ·
`other` account and security, finance, housing, health, IT, library, phishing.

`boundary_category` marks three mails that sit between two categories.

## Time expressions

Each time expression that matters is one item with a role:

| Role | Meaning | What a correct system does |
|---|---|---|
| `deadline` | Something the student must do by this date (coursework, exam, payment, a reply that was asked for by a date) | An open task with this date |
| `optional` | A date for something the student may choose to do | No required task |
| `non_task` | A real time that is not student work: event time, receipt stamp, code lifetime, offer end, billing date, cancelled item, quoted old request | No open task |
| `completed` | A due date quoted in a receipt for work already handed in | Not open again |

Rules for dates:

- `date` is what the mail states or what follows unambiguously from the sending date ("this Friday", "tomorrow",
  "one day before the appointment").
- `date = null` when the mail does not allow one answer: weekday and date disagree (`synA06`), or the date needs
  an academic calendar that the mail does not give (`synA07`). Guessing counts as a wrong date.
- `accept_dates` lists every acceptable answer; "within 5 days of this email" accepts the computed day or null.
- `time` is null when no time is written. Filling in 23:59 is reported as an invented time.
- `accept_times` lists acceptable times; for a test or inspection with a start and an end, both are accepted.
- `timezone` is set only when the mail names one (SGT, UTC).
- `current: false` marks a mention that a later mail replaced (`synA01`, `synA02` after the extension in `synA03`).
- `anchors` are the exact words in the mail that carry the item, used to pair a prediction with an item when the
  dates differ.

## Change log

- 2026-11-10: v1 created and frozen. No changes.
- 2026-11-10: every mail and answer checked by a person. Two answers corrected: `synP01` ("offer ends ... at
  midnight") and `synP07` ("0点前") now carry the time 00:00 instead of no time. Both are promotion end times
  (`non_task`), so no score changed. Frozen v1 hash of `labels.json` before this change:
  `22e27bb9df04836a7d2b117dfccabe350fb7a5eff28c8155c949abeba78fe704`; `MANIFEST.json` now records the new hash.
