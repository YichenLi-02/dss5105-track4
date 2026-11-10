"""Time-saved pilot: the same person handles one block of mail by hand and one block with the assistant's output.

    src/backend/.venv/bin/python scripts/time-pilot.py start --participant 1   # about 15 minutes, in a terminal
    src/backend/.venv/bin/python scripts/time-pilot.py summary --mails-per-week 120

For each mail the participant answers three things: does it need a reply, does it need an action, and which
deadline date(s) it sets. In the manual block only the mail is shown. In the assisted block the assistant's summary,
labels and tasks (from a saved evaluation run) are shown first and pre-filled; the participant accepts or corrects
them, so the time includes checking the assistant.

Two fixed blocks of 15 fictional mails with the same category mix are used. Odd-numbered participants do block A by
hand and block B assisted; even-numbered participants the other way round, and they start with the assisted block.
This balances mail difficulty and practice between the two conditions. Results go to
local-data/eval/time-pilot/<participant>.csv; nothing leaves the machine and no model is called.

This measures triage and deadline tracking only. Planning time is not measured.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "synthetic" / "mail_eval_v1"
PREDICTIONS = ROOT / "docs" / "evaluation" / "results" / "mail_synthetic_run1.predictions.json"
OUT = ROOT / "local-data" / "eval" / "time-pilot"
PER_BLOCK = {"academic": 6, "career": 2, "events": 2, "promotions": 2, "other": 3}
FIELDS = ["participant", "mode", "block", "position", "mail", "seconds", "reply", "action", "dates",
          "labels_correct", "dates_correct", "changed_assistant_answer"]


def blocks() -> tuple[dict, dict, dict]:
    msgs = {m["id"]: m for m in (json.loads(x) for x in (DATASET / "messages.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())}
    key = json.loads((DATASET / "labels.json").read_text(encoding="utf-8"))["messages"]
    rng = random.Random(5105)
    out = {"A": [], "B": []}
    for cat, n in PER_BLOCK.items():
        ids = sorted(i for i, g in key.items() if g["category"] == cat)
        rng.shuffle(ids)
        out["A"] += ids[:n]
        out["B"] += ids[n:2 * n]
    for b in out.values():
        rng.shuffle(b)
    return msgs, key, out


def expected_dates(gt: dict) -> list[str]:
    return sorted({it["date"] for it in gt["items"] if it["role"] == "deadline" and it.get("current", True) and it["date"]})


def ask(prompt: str, default: str | None = None) -> str:
    raw = input(f"{prompt}{f' [{default}]' if default is not None else ''}: ").strip()
    return raw if raw else (default or "")


def yes(prompt: str, default: bool | None = None) -> bool:
    while True:
        a = ask(prompt + " (y/n)", None if default is None else ("y" if default else "n")).lower()
        if a in ("y", "n"):
            return a == "y"


def one_mail(m: dict, gt: dict, pred: dict | None) -> dict:
    print("\n" * 3 + "=" * 78)
    print(f"From:    {m['from']}\nDate:    {m['sent_at']}\nSubject: {m['subject']}\n\n{m['body']}\n" + "-" * 78)
    d_reply = d_action = None
    d_dates = None
    if pred:
        lab = pred.get("labels") or {}
        tasks = [t for t in pred.get("tasks") or [] if t["state"] == "pending"]
        d_reply, d_action = bool(lab.get("needs_reply")), bool(lab.get("needs_action"))
        d_dates = ",".join(sorted({t["date"] for t in tasks if t["date"]}))
        print(f"ASSISTANT  summary: {pred.get('summary_en') or pred.get('summary')}")
        print(f"           needs reply: {'yes' if d_reply else 'no'}   needs action: {'yes' if d_action else 'no'}")
        for t in tasks:
            print(f"           task: {t.get('title_en') or t['title']}  |  {t['date'] or 'no date'} {t['time'] or ''}")
        print("-" * 78)
    t0 = time.monotonic()
    reply = yes("Needs a reply?", d_reply)
    action = yes("Needs an action besides replying?", d_action)
    dates = ask("Deadline date(s) you must meet, YYYY-MM-DD, comma-separated, empty for none", d_dates)
    seconds = time.monotonic() - t0
    got = sorted({x.strip() for x in dates.split(",") if x.strip()})
    return {"seconds": round(seconds, 1), "reply": reply, "action": action, "dates": ";".join(got),
            "labels_correct": reply == gt["needs_reply"] and action == gt["needs_action"],
            "dates_correct": got == expected_dates(gt),
            "changed_assistant_answer": bool(pred) and (reply != d_reply or action != d_action or ",".join(got) != (d_dates or ""))}


def cmd_start(args) -> int:
    msgs, key, blk = blocks()
    preds = json.loads(PREDICTIONS.read_text(encoding="utf-8"))["predictions"] if PREDICTIONS.is_file() else None
    if preds is None:
        print(f"missing {PREDICTIONS.relative_to(ROOT)}: run scripts/eval-mail.py run --set synthetic --run 1 first")
        return 1
    odd = args.participant % 2 == 1
    plan = [("manual", "A"), ("assisted", "B")] if odd else [("assisted", "A"), ("manual", "B")]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"participant{args.participant}.csv"
    if path.exists() and not args.redo:
        print(f"{path.relative_to(ROOT)} exists; use --redo to replace it")
        return 1
    print(__doc__.split("\n\n")[1])
    print("\nThe timer starts when a mail is shown and stops after the third answer. Work at your normal pace.")
    rows = []
    for mode, name in plan:
        input(f"\n>>> Next block: {len(blk[name])} mails, {mode.upper()}. Press Enter to start.")
        for pos, mid in enumerate(blk[name][:args.limit] if args.limit else blk[name], 1):
            r = one_mail(msgs[mid], key[mid], preds.get(mid) if mode == "assisted" else None)
            rows.append({"participant": args.participant, "mode": mode, "block": name, "position": pos, "mail": mid, **r})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {path.relative_to(ROOT)}. Thank you.")
    return 0


def cmd_summary(args) -> int:
    rows = []
    for p in sorted(OUT.glob("participant*.csv")):
        with p.open(encoding="utf-8") as f:
            rows += list(csv.DictReader(f))
    if not rows:
        print("no pilot results yet under", OUT.relative_to(ROOT))
        return 1
    people = sorted({r["participant"] for r in rows}, key=int)
    print(f"participants: {len(people)}; mails timed: {len(rows)}\n")
    print("| Condition | Mails | Mean s/mail | Median s/mail | Labels right | Dates right |\n|---|---|---|---|---|---|")
    mean = {}
    for mode in ("manual", "assisted"):
        g = [r for r in rows if r["mode"] == mode]
        if not g:
            continue
        s = [float(r["seconds"]) for r in g]
        mean[mode] = statistics.mean(s)
        print(f"| {mode} | {len(g)} | {mean[mode]:.1f} | {statistics.median(s):.1f} | "
              f"{sum(r['labels_correct'] == 'True' for r in g) / len(g):.0%} | {sum(r['dates_correct'] == 'True' for r in g) / len(g):.0%} |")
    if len(mean) == 2:
        saved = mean["manual"] - mean["assisted"]
        share = f"{saved / mean['manual']:.0%}" if mean["manual"] else "n/a"
        print(f"\nTime saved per mail: {saved:.1f} s ({share} of the manual time).")
        print(f"At {args.mails_per_week} mails a week: {saved * args.mails_per_week / 3600:.2f} hours a week "
              "(triage and deadline tracking only; the weekly volume is your own assumption, state it).")
        per = []
        for p in people:
            m = [float(r["seconds"]) for r in rows if r["participant"] == p and r["mode"] == "manual"]
            a = [float(r["seconds"]) for r in rows if r["participant"] == p and r["mode"] == "assisted"]
            if m and a:
                per.append((p, statistics.mean(m) - statistics.mean(a)))
        print("Per participant (s saved per mail): " + ", ".join(f"P{p}: {d:+.1f}" for p, d in per))
        changed = [r for r in rows if r["mode"] == "assisted"]
        print(f"Assistant answers the participant changed: {sum(r['changed_assistant_answer'] == 'True' for r in changed)}/{len(changed)}")
    print("\nSmall pilot on fictional mail: report it as a pilot, with the number of participants, not as a measured saving.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="run the two timed blocks for one participant")
    s.add_argument("--participant", type=int, required=True)
    s.add_argument("--limit", type=int, default=0, help="only the first N mails of each block (for a dry run)")
    s.add_argument("--redo", action="store_true")
    s.set_defaults(fn=cmd_start)
    r = sub.add_parser("summary", help="combine all participants")
    r.add_argument("--mails-per-week", type=int, default=120)
    r.set_defaults(fn=cmd_summary)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
