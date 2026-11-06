"""Run the planner evaluation and write the report (same structure every run).

    src\\backend\\.venv\\Scripts\\python scripts\\eval-planner.py            # 27 fixed + 200 seeded + conflict repairs
    src\\backend\\.venv\\Scripts\\python scripts\\eval-planner.py --n 500 --seed 7

Writes local-data/planner-eval/report.json and report.md. Uses only the planning rules - no database, calendar,
model or network. Exit code 1 if a fixed scenario fails (other than a documented known gap) or any seeded
scenario or repaired plan breaks a hard rule.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/backend"))
from evaluation import planner_eval  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=200, help="number of seeded scenarios (default 200)")
    ap.add_argument("--seed", type=int, default=planner_eval.SEED, help=f"random seed (default {planner_eval.SEED})")
    ap.add_argument("--out", type=Path, default=ROOT / "local-data/planner-eval")
    args = ap.parse_args()
    rep = planner_eval.build_report(args.n, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "report.md").write_text(planner_eval.markdown(rep), encoding="utf-8")
    f, s = rep["fixed"], rep["seeded"]
    unexpected = [x for x in f["failed"] if x not in f["known_gaps"]]
    print(f"fixed: {f['passed']}/{f['total']} passed; known gaps: {', '.join(f['known_gaps']) or 'none'}")
    print(f"seeded: {s['count']} scenarios (seed {s['seed']}), status {s['by_status']}")
    print(f"        hard-rule violations in {s['scenarios_with_any_violation']} scenario(s); "
          f"coverage mean {s['coverage']['mean']}, min {s['coverage']['min']}")
    r = rep["repairs"]
    print(f"repairs: {r['count']} scenarios with a new meeting; hard-rule violations {r['hard_violations']}; "
          f"blocks changed {r['avg_changed']} vs full re-plan {r['avg_changed_full_replan']}; "
          f"rules relaxed in the recommended fix {r['relaxed_recommended']}")
    c = rep["calibration"]
    print(f"calibration (simulated students): median estimate error {c['raw_median_error']:.1%} -> "
          f"{c['calibrated_median_error']:.1%}; underestimators {c['by_group']['under']['raw_median_error']:.1%} -> "
          f"{c['by_group']['under']['calibrated_median_error']:.1%}")
    print(f"report: {args.out / 'report.md'}")
    return 1 if unexpected or s["scenarios_with_any_violation"] or r["hard_violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
