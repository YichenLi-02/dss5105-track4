"""Mail evaluation: run the real pipeline on a mail set, save what it produced, then score it.

    src/backend/.venv/bin/python scripts/eval-mail.py smoke                       # 2 throwaway mails, checks the plumbing
    src/backend/.venv/bin/python scripts/eval-mail.py run --set synthetic --run 1 # 80 fictional mails (calls the model)
    src/backend/.venv/bin/python scripts/eval-mail.py run --set samples --run 1   # 40 de-identified sample mails
    src/backend/.venv/bin/python scripts/eval-mail.py score                       # (re)score every saved run, no model

"run" needs the model settings from .env (LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL, ALLOW_MODEL_PROCESSING) and
spends tokens: about 2,400 per mail. Each run uses its own empty database under local-data/eval/, never the app's
own data, keeps tokens in memory instead of the system keychain, runs in demo mode with external writes off, and
routes every outbound request through a transport that only lets the model endpoint through.

Saved under docs/evaluation/results/: <name>.predictions.json (raw output), <name>.report.json / .report.md
(scores and every error), and mail_summary.md (all runs side by side).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "synthetic" / "mail_eval_v1"
SAMPLES = ROOT / "data" / "AI项目数据源_去隐私"
RESULTS = ROOT / "docs" / "evaluation" / "results"
WORK = ROOT / "local-data" / "eval"
sys.path.insert(0, str(ROOT / "src" / "backend"))

SMOKE = [
    {"id": "smoke1", "thread_id": "t1", "sent_at": "2026-12-01T09:00:00+08:00", "from": "Tutor <tutor@smoke.example>",
     "to": "me@smoke.example", "subject": "Worksheet 9", "label_ids": ["INBOX"],
     "body": "Hello,\n\nWorksheet 9 is due on 18 December 2026 at 17:00. Call 6123 4567 if the portal is down.\n\nTutor"},
    {"id": "smoke2", "thread_id": "t2", "sent_at": "2026-12-01T10:00:00+08:00", "from": "Shop <deals@smoke.example>",
     "to": "me@smoke.example", "subject": "Winter sale", "label_ids": ["INBOX"],
     "body": "Everything is 20% off until 5 December. Shop now at https://smoke.example/sale"},
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def pipeline(name: str, mail_set: str, batch: int) -> tuple[dict, dict]:
    work = WORK / name
    assert WORK in work.parents
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    os.environ.update({"DATA_DIR": str(work), "DATABASE_PATH": str(work / "eval.sqlite3"), "APP_MODE": "demo",
                       "ENABLE_EXTERNAL_WRITES": "false", "SAMPLE_DATA_DIR": ""})
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.llm import adapter
    from app.main import app
    from app.providers import net
    from evaluation import mail_eval as M
    assert settings.database_path.resolve() == (work / "eval.sqlite3").resolve(), settings.database_path
    assert settings.app_mode == "demo" and not settings.enable_external_writes

    dataset = None
    if mail_set == "synthetic":
        messages, _ = M.load_synthetic(DATASET)
        manifest = json.loads((DATASET / "MANIFEST.json").read_text(encoding="utf-8"))
        for fname, want in manifest["sha256"].items():
            got = hashlib.sha256((DATASET / fname).read_bytes()).hexdigest()
            assert got == want, f"{fname} differs from the frozen manifest"
        dataset = {"version": manifest["version"], "sha256": manifest["sha256"]}
    elif mail_set == "smoke":
        messages = SMOKE
    else:
        messages = []
        dataset = {"version": "selected_50", "sha256": {f: hashlib.sha256((SAMPLES / f).read_bytes()).hexdigest()
                                                         for f in ("selected_50.jsonl", "date_candidates.jsonl")}}
    started = _now()
    with TestClient(app) as client:
        api = M.Api(client)
        router = M.connect(messages)
        try:
            stored = M.sync_mailbox(api, len(messages)) if messages else M.import_samples(api)
            print(f"[{name}] stored: {stored}", flush=True)
            status = M.enable_model(api)
            info = M.analyse(api, batch=batch, log=lambda s: print(f"[{name}]{s}", flush=True))
            preds = M.collect(api, info["errors"])
        finally:
            net.set_transport(None)
    meta = {"name": name, "mail_set": mail_set, "started_at": started, "finished_at": _now(), "provider": status["provider"],
            "model": status["model"], "prompt_version": status["prompt_version"], "schema_version": adapter.SCHEMA_VERSION,
            "code_commit": _git("rev-parse", "--short", "HEAD"),
            "app_code_modified": bool(_git("status", "--porcelain", "--", "src/backend/app", "src/frontend/src")),
            "dataset": dataset, "messages": info["messages"], "analysis_seconds": info["seconds"],
            "first_pass_errors": info["first_pass_errors"], "errors": info["errors"], "retried": info["retried"],
            "outbound_calls": dict(router.calls), "refused_requests": router.refused, "stored": stored}
    return meta, preds


def cmd_run(args) -> int:
    name = f"mail_{args.set}_run{args.run}"
    meta, preds = pipeline(name, args.set, args.batch)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{name}.predictions.json"
    out.write_text(json.dumps({"meta": meta, "predictions": preds}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{name}] done: {meta['messages']} mails in {meta['analysis_seconds']} s, {len(meta['errors'])} failed, "
          f"outbound {meta['outbound_calls']}, refused {len(meta['refused_requests'])} -> {out.relative_to(ROOT)}")
    return 0


def cmd_smoke(args) -> int:
    meta, preds = pipeline("smoke", "smoke", 2)
    for sid, p in preds.items():
        print(f"\n{sid}: status={p['analysis_status']} labels={p['labels']} error={p['error']}")
        print(f"  stored subject={p['subject']!r}\n  stored body={p['body_view']!r}")
        for t in p["tasks"]:
            print(f"  task: {t['title']!r} {t['state']} {t['date']} {t['time']} tz={t['timezone']} quote={t['quote']!r} span=({t['start']},{t['end']})")
    print(f"\nmeta: model={meta['model']} seconds={meta['analysis_seconds']} errors={meta['errors']} "
          f"outbound={meta['outbound_calls']} refused={meta['refused_requests']}")
    return 0


def cmd_score(args) -> int:
    from evaluation import mail_eval as M
    files = sorted(RESULTS.glob("mail_*_run*.predictions.json"))
    if not files:
        print("no saved predictions under", RESULTS)
        return 1
    keys = {"synthetic": M.load_synthetic(DATASET)[1], "samples": M.load_samples(SAMPLES)}
    by_set: dict[str, list[tuple[str, dict]]] = {}
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        name, mail_set = doc["meta"]["name"], doc["meta"]["mail_set"]
        rep = M.build_report(keys[mail_set], doc["predictions"], doc["meta"])
        (RESULTS / f"{name}.report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        (RESULTS / f"{name}.report.md").write_text(M.markdown(name, rep), encoding="utf-8")
        by_set.setdefault(mail_set, []).append((name, rep))
        t, d = rep["triage"], rep["deadlines"]
        print(f"{name}: reply F1 {t['labels']['needs_reply']['f1']}, action F1 {t['labels']['needs_action']['f1']}, "
              f"exact {t['exact_match']['value']}, category {t['category_accuracy']['value']}; deadline recall "
              f"{d['recall_per_mail']['value']} / unique {d['recall_unique']['value']}, precision "
              f"{d['precision_per_mail']['value']} / list {d['precision_task_list']['value']}; "
              f"open tasks {d['system_output']['open']}, failed {len(d['system_output']['mails_analysis_failed'])}")
    summary = {s: {"runs": [n for n, _ in reps], "label_status": reps[0][1]["answer_key"]["label_status"],
                   "aggregate": M.aggregate([r for _, r in reps])} for s, reps in by_set.items()}
    (RESULTS / "mail_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# Mail evaluation - all runs", ""]
    for s, x in summary.items():
        L += [f"## {s}", "", f"Runs: {', '.join(x['runs'])}. Labels: {x['label_status']}.", "",
              "| Measure | Mean | Min | Max |", "|---|---|---|---|"]
        L += [f"| {k} | {v.get('mean')} | {v.get('min')} | {v.get('max')} |" for k, v in x["aggregate"].items()]
        L.append("")
    (RESULTS / "mail_summary.md").write_text("\n".join(L), encoding="utf-8")
    print(f"reports written to {RESULTS.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline on a mail set and save the predictions (calls the model)")
    r.add_argument("--set", choices=["synthetic", "samples"], required=True)
    r.add_argument("--run", type=int, default=1)
    r.add_argument("--batch", type=int, default=8)
    r.set_defaults(fn=cmd_run)
    sub.add_parser("smoke", help="two throwaway mails through the whole pipeline").set_defaults(fn=cmd_smoke)
    sub.add_parser("score", help="score every saved run and write the reports (no model call)").set_defaults(fn=cmd_score)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
