"""Check manually authored Sprint 1 plans. This is not a scheduling engine."""

import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Every timestamp must include a UTC offset")
    return parsed


def span(block):
    return instant(block["start"]), instant(block["end"])


def minutes(block):
    start, end = span(block)
    return (end - start).total_seconds() / 60


def overlaps(a, b):
    a_start, a_end = span(a)
    b_start, b_end = span(b)
    return a_start < b_end and b_start < a_end


def check_case(case, settings):
    request, plan = case["input"], case["reference_plan"]
    now, zone = instant(request["now"]), ZoneInfo(request["timezone"])
    tasks = {task["id"]: task for task in request["tasks"]}
    blocks = plan["blocks"]
    locked = request["locked_blocks"]
    completed = request["completed_blocks"]
    issues = []
    new_total = defaultdict(float)
    fixed_total = defaultdict(float)
    daily = defaultdict(float)
    warnings = {(item["code"], item["task_id"]) for item in plan["warnings"]}
    unscheduled = {item["task_id"]: item["minutes"] for item in plan["unscheduled"]}
    buffers = {}

    def reject(code, detail):
        issues.append({"code": code, "detail": detail})

    for block in blocks:
        task = tasks.get(block["task_id"])
        start, end = span(block)
        duration = minutes(block)
        if duration <= 0:
            reject("INVALID_INTERVAL", block["task_id"])
        if not task or not task["confirmed"] or not task["due_at"]:
            reject("UNCONFIRMED_SCHEDULE", block["task_id"])
            continue
        if start < now:
            reject("PAST_START", block["task_id"])
        if end > instant(task["due_at"]):
            reject("AFTER_DEADLINE", block["task_id"])
        local_start, local_end = start.astimezone(zone), end.astimezone(zone)
        day_start = time.fromisoformat(settings["study_day_start"])
        day_end = time.fromisoformat(settings["study_day_end"])
        if local_start.date() != local_end.date() or not (
            day_start <= local_start.time().replace(tzinfo=None)
            < local_end.time().replace(tzinfo=None) <= day_end
        ):
            reject("OUTSIDE_STUDY_HOURS", block["task_id"])
        if duration > settings["max_block_minutes"]:
            reject("LONG_BLOCK", block["task_id"])
        if any(t.minute % settings["time_step_minutes"] or t.second for t in (start, end)):
            reject("OFF_GRID", block["task_id"])
        if not any(span(window)[0] <= start and end <= span(window)[1]
                   for window in request["availability"]):
            reject("OUTSIDE_AVAILABILITY", block["task_id"])
        if any(overlaps(block, occupied) for occupied in request["busy"] + locked):
            reject("BUSY_OVERLAP", block["task_id"])
        new_total[block["task_id"]] += duration

    for index, block in enumerate(blocks):
        if any(overlaps(block, other) for other in blocks[index + 1:]):
            reject("PLAN_OVERLAP", block["task_id"])
    for block in locked:
        fixed_total[block["task_id"]] += minutes(block)
    for block in blocks + locked + completed:
        daily[span(block)[0].astimezone(zone).date().isoformat()] += minutes(block)
    for day, total in daily.items():
        if total > settings["max_study_minutes_per_day"]:
            reject("DAILY_OVERLOAD", day)

    # A short gap does not reset the continuous-study counter.
    running, last_end = 0, None
    for block in sorted(blocks + locked + completed, key=lambda item: span(item)[0]):
        start, end = span(block)
        if last_end is None or (start - last_end).total_seconds() / 60 >= settings["min_break_minutes"]:
            running = 0
        running += minutes(block)
        if running > settings["max_block_minutes"]:
            reject("CONTINUOUS_OVERLOAD", block["task_id"])
        last_end = end

    if plan.get("retained_locked_blocks", []) != locked:
        reject("LOCKED_CHANGED", "A retained locked block differs from the request")
    for task_id, task in tasks.items():
        if not task["due_at"]:
            if ("MISSING_DUE_AT", task_id) not in warnings:
                reject("MISSING_INPUT_WARNING", task_id)
            continue
        if not task["confirmed"]:
            if ("UNCONFIRMED_TASK", task_id) not in warnings:
                reject("MISSING_CONFIRMATION_WARNING", task_id)
            continue
        reserved = ((task["remaining_minutes"] + 14) // 15) * 15
        if new_total[task_id] + fixed_total[task_id] + unscheduled.get(task_id, 0) != reserved:
            reject("ACCOUNTING_MISMATCH", task_id)
        if unscheduled.get(task_id, 0) and ("INSUFFICIENT_TIME", task_id) not in warnings:
            reject("MISSING_SHORTAGE_WARNING", task_id)
        finishing = [span(block)[1] for block in blocks + locked if block["task_id"] == task_id]
        if finishing:
            buffer_minutes = (instant(task["due_at"]) - max(finishing)).total_seconds() / 60
            buffers[task_id] = buffer_minutes / 60
            if buffer_minutes < settings["target_buffer_minutes"] and ("LOW_BUFFER", task_id) not in warnings:
                reject("MISSING_BUFFER_WARNING", task_id)

    total_new = sum(new_total.values())
    total_missing = sum(unscheduled.values())
    if plan["status"] == "complete" and total_missing:
        reject("FALSE_COMPLETE", "Work remains unscheduled")
    if total_new != case["expected"]["scheduled_minutes"]:
        reject("EXPECTED_TOTAL", "Scheduled minutes differ from the reference target")
    if total_missing != case["expected"]["unscheduled_minutes"]:
        reject("EXPECTED_SHORTAGE", "Missing minutes differ from the reference target")
    return {
        "case_id": case["id"], "category": case["category"], "passed": not issues,
        "scheduled_minutes": total_new, "unscheduled_minutes": total_missing,
        "buffer_hours": buffers, "daily_minutes": dict(daily), "issues": issues
    }


def sentinel_checks(cases, settings):
    by_id = {case["id"]: case for case in cases}
    checks = []
    variants = []
    night = copy.deepcopy(by_id["normal_week"])
    night["reference_plan"]["blocks"][0].update(start="2026-10-12T02:00:00+08:00", end="2026-10-12T03:30:00+08:00")
    variants.append(("night_session", night, "OUTSIDE_STUDY_HOURS"))
    late = copy.deepcopy(by_id["normal_week"])
    late["reference_plan"]["blocks"][0].update(start="2026-10-15T18:00:00+08:00", end="2026-10-15T19:30:00+08:00")
    variants.append(("after_deadline", late, "AFTER_DEADLINE"))
    clash = copy.deepcopy(by_id["normal_week"])
    clash["reference_plan"]["blocks"][2].update(start="2026-10-13T09:00:00+08:00", end="2026-10-13T10:30:00+08:00")
    variants.append(("double_booking", clash, "PLAN_OVERLAP"))
    hidden = copy.deepcopy(by_id["capacity_shortage"])
    hidden["reference_plan"]["warnings"] = []
    variants.append(("hidden_shortage", hidden, "MISSING_SHORTAGE_WARNING"))
    moved = copy.deepcopy(by_id["meeting_replan"])
    moved["reference_plan"]["retained_locked_blocks"][0]["start"] = "2026-10-15T09:30:00+08:00"
    variants.append(("moved_locked_block", moved, "LOCKED_CHANGED"))
    for name, case, expected_code in variants:
        actual = check_case(case, settings)
        detected = expected_code in {item["code"] for item in actual["issues"]}
        checks.append({"name": name, "expected_code": expected_code, "detected": detected})
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    source = json.loads((root / "reference_cases.json").read_text(encoding="utf-8"))
    results = [check_case(case, source["settings"]) for case in source["cases"]]
    sentinels = sentinel_checks(source["cases"], source["settings"])
    all_passed = all(item["passed"] for item in results) and all(item["detected"] for item in sentinels)
    report = {
        "scope": "Manual synthetic reference-plan checks only. No scheduler, LLM, Graph integration, user study or held-out evaluation has been tested.",
        "all_passed": all_passed, "reference_checks": results, "invalid_output_sentinels": sentinels
    }
    if args.write_report:
        (root / "reference_case_checks.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
