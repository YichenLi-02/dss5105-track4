"""Independent plan checker, ported from member 4's check_reference_cases.py (branch zhaozichen, commit 9d0fc1a).

It does not share code with the engine on purpose: a plan is saved only if this separate check finds no issue.
Issue codes match member 4's script so results can be compared directly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import time
from zoneinfo import ZoneInfo

from ..models import PlanRequest, PlanResult


def _mins(a, b) -> float:
    return (b - a).total_seconds() / 60


def _overlap(a, b) -> bool:
    return a.start < b.end and b.start < a.end


def check_plan(request: PlanRequest, plan: PlanResult) -> list[dict]:
    s = request.settings
    zone = ZoneInfo(request.timezone)
    tasks = {t.id: t for t in request.tasks}
    locked, completed = request.locked_blocks, request.completed_blocks
    warnings = {(w.code, w.task_id) for w in plan.warnings}
    unscheduled = {u.task_id: u.minutes for u in plan.unscheduled}
    issues: list[dict] = []
    new_total: dict[str, float] = defaultdict(float)
    fixed_total: dict[str, float] = defaultdict(float)
    daily: dict[str, float] = defaultdict(float)
    day_start, day_end = time.fromisoformat(s.study_day_start), time.fromisoformat(s.study_day_end)

    def reject(code: str, detail: str | None) -> None:
        issues.append({"code": code, "detail": detail})

    for block in plan.blocks:
        task = tasks.get(block.task_id)
        duration = _mins(block.start, block.end)
        if duration <= 0:
            reject("INVALID_INTERVAL", block.task_id)
        if not task or not task.confirmed or not task.due_at:
            reject("UNCONFIRMED_SCHEDULE", block.task_id)
            continue
        if block.start < request.now:
            reject("PAST_START", block.task_id)
        if block.end > task.due_at:
            reject("AFTER_DEADLINE", block.task_id)
        ls, le = block.start.astimezone(zone), block.end.astimezone(zone)
        if ls.date() != le.date() or not (day_start <= ls.time().replace(tzinfo=None) < le.time().replace(tzinfo=None) <= day_end):
            reject("OUTSIDE_STUDY_HOURS", block.task_id)
        if duration > s.max_block_minutes:
            reject("LONG_BLOCK", block.task_id)
        if any(t.minute % s.time_step_minutes or t.second for t in (block.start, block.end)):
            reject("OFF_GRID", block.task_id)
        if not any(w.start <= block.start and block.end <= w.end for w in request.availability):
            reject("OUTSIDE_AVAILABILITY", block.task_id)
        if any(_overlap(block, other) for other in [*request.busy, *locked]):
            reject("BUSY_OVERLAP", block.task_id)
        new_total[block.task_id] += duration

    for i, block in enumerate(plan.blocks):
        if any(_overlap(block, other) for other in plan.blocks[i + 1:]):
            reject("PLAN_OVERLAP", block.task_id)
    for block in locked:
        fixed_total[block.task_id] += _mins(block.start, block.end)
    for block in [*plan.blocks, *locked, *completed]:
        daily[block.start.astimezone(zone).date().isoformat()] += _mins(block.start, block.end)
    for day, total in daily.items():
        if total > s.max_study_minutes_per_day:
            reject("DAILY_OVERLOAD", day)

    running, last_end = 0.0, None
    for block in sorted([*plan.blocks, *locked, *completed], key=lambda b: b.start):
        if last_end is None or _mins(last_end, block.start) >= s.min_break_minutes:
            running = 0.0
        running += _mins(block.start, block.end)
        if running > s.max_block_minutes:
            reject("CONTINUOUS_OVERLOAD", block.task_id)
        last_end = block.end

    if plan.retained_locked_blocks != list(locked):
        reject("LOCKED_CHANGED", "a retained locked block differs from the request")
    for task_id, task in tasks.items():
        if not task.due_at:
            if ("MISSING_DUE_AT", task_id) not in warnings:
                reject("MISSING_INPUT_WARNING", task_id)
            continue
        if not task.confirmed:
            if ("UNCONFIRMED_TASK", task_id) not in warnings:
                reject("MISSING_CONFIRMATION_WARNING", task_id)
            continue
        reserved = ((task.remaining_minutes + 14) // 15) * 15
        if new_total[task_id] + fixed_total[task_id] + unscheduled.get(task_id, 0) != reserved:
            # locked work can exceed the remaining estimate; that is reported, not double counted
            if not (fixed_total[task_id] >= reserved and new_total[task_id] == 0):
                reject("ACCOUNTING_MISMATCH", task_id)
        if unscheduled.get(task_id, 0) and ("INSUFFICIENT_TIME", task_id) not in warnings:
            reject("MISSING_SHORTAGE_WARNING", task_id)
        finishing = [b.end for b in [*plan.blocks, *locked] if b.task_id == task_id]
        if finishing:
            buffer_minutes = _mins(max(finishing), task.due_at)
            if buffer_minutes < s.target_buffer_minutes and ("LOW_BUFFER", task_id) not in warnings:
                reject("MISSING_BUFFER_WARNING", task_id)

    if plan.status == "complete" and sum(unscheduled.values()):
        reject("FALSE_COMPLETE", "work remains unscheduled")
    return issues
