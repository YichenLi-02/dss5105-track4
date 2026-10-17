"""Weekly planner (member 4's area). `build_request` assembles the planner input from stored data;
`generate` turns a PlanRequest into a PlanResult and is implemented in P1 from member 4's rules and
reference cases (tests/fixtures/reference_cases.json).

Input semantics follow the reference cases:
- remaining_minutes is the work still to do, including any locked future blocks of that task
- completed_blocks are past work; they count toward the daily limit but not toward remaining work
- locked_blocks are kept exactly as they are when the plan is regenerated
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..models import Interval, PlanBlock, PlanRequest, PlanResult, PlanSettings, PlanTask, PlanWarning, Progress, Task, TimeSlot


class NotImplementedYet(Exception):
    pass


def build_request(
    tasks: list[Task],
    slots: list[TimeSlot],
    now: datetime,
    progress: list[Progress] | None = None,
    locked_blocks: list[PlanBlock] | None = None,
    settings: PlanSettings | None = None,
) -> PlanRequest:
    plan_tasks = [
        PlanTask(
            id=t.task_id,
            title=t.title,
            due_at=t.due_at,
            remaining_minutes=t.remaining_minutes,
            priority=t.priority,
            confirmed=t.confirmed,
        )
        for t in tasks
        if t.status == "open" and t.kind == "deliverable" and t.remaining_minutes > 0
    ]
    # an event (exam, meeting) is time the student cannot study
    event_busy = [
        Interval(start=t.due_at, end=t.due_at + _event_length(t))
        for t in tasks
        if t.kind == "event" and t.status == "open" and t.due_at > now
    ]
    return PlanRequest(
        now=now,
        tasks=plan_tasks,
        availability=[Interval(start=s.start, end=s.end) for s in slots if s.kind == "available" and s.end > now],
        busy=[Interval(start=s.start, end=s.end) for s in slots if s.kind == "busy" and s.end > now] + event_busy,
        completed_blocks=[PlanBlock(task_id=p.task_id, start=p.start, end=p.end) for p in (progress or [])],
        locked_blocks=[b for b in (locked_blocks or []) if b.end > now],
        settings=settings or PlanSettings(),
    )


def _event_length(task: Task) -> timedelta:
    """For an event, remaining_minutes holds its length; one hour when unknown."""
    return timedelta(minutes=task.remaining_minutes or 60)


def generate(request: PlanRequest) -> PlanResult:
    """Placeholder until the P1 engine lands: reports what would be planned without placing blocks."""
    raise NotImplementedYet("the planning engine is part of P1")


def preview(request: PlanRequest) -> PlanResult:
    """Inputs check used by the API until `generate` exists: flags tasks that cannot be planned."""
    warnings: list[PlanWarning] = []
    for t in request.tasks:
        if t.due_at is None:
            warnings.append(PlanWarning(code="MISSING_DUE_AT", task_id=t.id, message=f"{t.title}: no deadline yet"))
        if not t.confirmed:
            warnings.append(PlanWarning(code="UNCONFIRMED_TASK", task_id=t.id, message=f"{t.title}: not confirmed"))
        if t.due_at is not None and t.due_at <= request.now:
            warnings.append(PlanWarning(code="PAST_DEADLINE", task_id=t.id, message=f"{t.title}: deadline has passed"))
    status = "needs_input" if warnings else "partial"
    return PlanResult(status=status, warnings=warnings, retained_locked_blocks=request.locked_blocks)
