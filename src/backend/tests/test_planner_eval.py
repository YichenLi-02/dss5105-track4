"""Planner evaluation (evaluation/planner_eval.py): hand-written fixed scenarios plus seeded scenarios."""
import pytest

from evaluation import planner_eval as E

FIXED = E.load_fixed()


@pytest.mark.parametrize("sc", FIXED, ids=[s["id"] for s in FIXED])
def test_fixed_scenario(sc):
    r = E.check_fixed(sc)
    failed = [c for c in r["checks"] if not c["ok"]]
    if sc.get("known_gap"):
        # A documented gap must still be honest: never "feasible" while work is missing, never a rule broken.
        assert r["metrics"]["status"] != "feasible" or r["metrics"]["unplaced"] == 0
        assert r["metrics"]["status"] != "feasible" or not failed
        assert next(c for c in r["checks"] if c["check"] == "hard_rule_violations")["ok"]
        return
    assert not failed, failed


def test_seeded_scenarios_break_no_hard_rule_and_repeat_exactly():
    a = E.score_seeded(200)
    assert a["count"] == 200 and a["scenarios_with_any_violation"] == 0, a["violations"]
    opt = a["single_task_optimality"]
    assert opt["checked"] >= 20 and opt["gap_minutes"] == 0, opt  # every single-task plan is the exhaustive optimum
    assert a["by_status"].get("feasible", 0) > 0 and a["by_status"].get("needs_information", 0) > 0
    assert E.score_seeded(200)["rows"] == a["rows"]  # same seed -> same scenarios and results


def test_report_has_a_stable_structure():
    rep = E.build_report(20)
    assert set(rep) == {"schema_version", "generated_at", "fixed", "seeded", "repairs", "calibration"}
    assert set(rep["fixed"]) == {"total", "passed", "failed", "known_gaps", "results"}
    assert {"by_status", "violations", "coverage", "unplaced_minutes_total", "rows"} <= set(rep["seeded"])
    assert rep["fixed"]["known_gaps"] == [] and rep["fixed"]["failed"] == []
    assert "single_task_optimality" in rep["seeded"] and "覆盖率" in E.markdown(rep) and "冲突修复" in E.markdown(rep)


def test_conflict_repairs_keep_every_rule_and_change_less_than_a_full_replan():
    r = E.score_repairs(200)
    assert r["count"] >= 150 and r["hard_violations"] == 0, [x for x in r["rows"] if x["hard_violations"]][:5]
    assert r["no_worse_than_full_replan"] == r["count"]  # never places less than planning again from scratch
    assert r["fewer_or_equal_changes"] == r["same_unmet_as_full_replan"]  # and moves no more blocks to do it
    assert r["relaxed_recommended"] == 0 and r["relaxed_needlessly"] == 0  # rules are relaxed only by explicit choice
    assert r["written_hits"] > 0 and r["written_moved"] == r["written_hits"]
    assert E.score_repairs(200)["rows"] == r["rows"]


def test_calibration_simulation_helps_without_adding_deadline_risk():
    c = E.score_calibration(200)
    g = c["by_group"]
    assert c["first_tasks_without_suggestion"]
    assert c["calibrated_median_error"] < c["raw_median_error"]
    assert g["under"]["calibrated_median_error"] < g["under"]["raw_median_error"]
    assert g["under"]["calibrated_underestimated"] < g["under"]["raw_underestimated"] / 2
    assert g["over"]["calibrated_median_error"] < g["over"]["raw_median_error"]
    assert g["over"]["calibrated_underestimated"] <= g["over"]["raw_underestimated"] + 5  # shortening stays safe
    assert g["accurate"]["calibrated_median_error"] <= g["accurate"]["raw_median_error"] + 0.01
    assert E.score_calibration(200) == c  # fixed seed: same numbers every run
