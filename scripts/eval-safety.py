"""Run the safety red-team (20 specifications) against the real application code.

    src/backend/.venv/bin/python scripts/eval-safety.py --run 1
    src/backend/.venv/bin/python scripts/eval-safety.py --merge      # combine saved runs, no model call

Needs the model settings from .env (about 25 model calls). Uses its own empty database under local-data/eval/safety,
keeps tokens in memory, and replaces every mail and calendar provider with a recorder: no real account is contacted
and nothing is sent. Each run writes docs/evaluation/results/safety_runN.json; safety.json and safety.md combine all
saved runs, taking the worst outcome per specification (model output varies between runs). Exit code 1 if any
specification fails.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs" / "evaluation" / "results"
sys.path.insert(0, str(ROOT / "src" / "backend"))


def merge() -> int:
    from evaluation import safety_eval as S
    runs = {int(f.stem.rsplit("run", 1)[1]): json.loads(f.read_text(encoding="utf-8")) for f in sorted(RESULTS.glob("safety_run*.json"))}
    if not runs:
        print("no saved safety runs")
        return 1
    rep = S.merge(runs)
    (RESULTS / "safety.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / "safety.md").write_text(S.markdown(rep), encoding="utf-8")
    print(f"runs {sorted(runs)}: {rep['counts']}  ->  {(RESULTS / 'safety.md').relative_to(ROOT)}")
    for r in rep["results"]:
        print(f"  {r['id']} {r['verdict']:14s} {r['by_run']}")
    return 1 if rep["counts"]["fail"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--merge", action="store_true", help="only combine the saved runs")
    args = ap.parse_args()
    if args.merge:
        return merge()
    WORK = ROOT / "local-data" / "eval" / f"safety-run{args.run}"
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    os.environ.update({"DATA_DIR": str(WORK), "DATABASE_PATH": str(WORK / "eval.sqlite3"), "APP_MODE": "demo",
                       "ENABLE_EXTERNAL_WRITES": "false", "SAMPLE_DATA_DIR": ""})
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.llm import adapter
    from app.main import app
    from app.providers import net
    from evaluation import safety_eval as S
    assert settings.database_path.resolve() == (WORK / "eval.sqlite3").resolve()
    assert settings.app_mode == "demo" and not settings.enable_external_writes
    with TestClient(app) as client:
        run = S.Run(client)
        try:
            print("mail-borne cases through the real pipeline (model calls)...", flush=True)
            run.run_mail()
            run.mail_checks()
            run.binding_checks()
            run.planning_checks()
            run.live_checks()
            run.capability_checks()
        finally:
            net.set_transport(None)
            settings.app_mode, settings.enable_external_writes = "demo", False
        rep = run.summary()
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    rep["meta"] = {"finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "model": settings.openai_model,
                   "prompt_version": adapter.PROMPT_VERSION, "code_commit": git("rev-parse", "--short", "HEAD"),
                   "app_code_modified": bool(git("status", "--porcelain", "--", "src/backend/app", "src/frontend/src"))}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"safety_run{args.run}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nrun {args.run}: {rep['counts']}")
    return merge()


if __name__ == "__main__":
    sys.exit(main())
