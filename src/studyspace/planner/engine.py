"""Rule-based weekly planner, following member 4's rules (github_upload/planner/README.md on branch zhaozichen).

Hard rules: only confirmed tasks with an exact deadline; never in the past, after the deadline, outside the study
window or the student's available hours; no overlap with classes, meetings, locked or other study blocks; at most
180 focused minutes a day (completed and locked work included); at most 90 minutes in a row, then a 15-minute break.
Preference: finish 24 hours before the deadline; when that is impossible, plan anyway and warn LOW_BUFFER.
Order: deadline, then priority, then task id. When time runs out the shortfall is reported per task, never hidden.

This is an explainable greedy method. It can miss a feasible plan in rare cases; it never relaxes a hard rule.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..models import (
    DEADLINE_CLUSTER,
    INSUFFICIENT_TIME,
    LOCK_CONFLICT,
    LOW_BUFFER,
    MISSING_DUE_AT,
    PAST_DEADLINE,
    UNCONFIRMED_TASK,
    Interval,
    PlanBlock,
    PlanRequest,
    PlanResult,
    PlanTask,
    PlanWarning,
    TaskResult,
    Unscheduled,
)

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
Span = tuple[datetime, datetime]


def round_up(minutes: int, step: int) -> int:
    return -(-minutes // step) * step


def _floor(dt: datetime, step: int) -> datetime:
    excess = (dt.minute % step) * 60 + dt.second + dt.microsecond / 1e6
    return dt - timedelta(seconds=excess)


def _ceil(dt: datetime, step: int) -> datetime:
    floored = _floor(dt, step)
    return floored if floored == dt else floored + timedelta(minutes=step)


def _minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def _subtract(spans: list[Span], cut: Span) -> list[Span]:
    out = []
    for a, b in spans:
        if cut[1] <= a or cut[0] >= b:
            out.append((a, b))
            continue
        if a < cut[0]:
            out.append((a, cut[0]))
        if cut[1] < b:
            out.append((cut[1], b))
    return out


class Planner:
    def __init__(self, request: PlanRequest):
        self.req = request
        self.s = request.settings
        self.zone = ZoneInfo(request.timezone)
        self.step = self.s.time_step_minutes
        self.now = _ceil(request.now.astimezone(self.zone), self.step)
        self.warnings: list[PlanWarning] = []
        # every block that already occupies time: completed work and locked future work
        self.existing: list[Span] = [(b.start.astimezone(self.zone), b.end.astimezone(self.zone))
                                     for b in [*request.completed_blocks, *request.locked_blocks]]
        self.new_blocks: list[PlanBlock] = []
        self.daily: dict[date, int] = defaultdict(int)
        for a, b in self.existing:
            self.daily[a.date()] += _minutes(a, b)

    # -- public ---------------------------------------------------------------------------------
    def run(self) -> PlanResult:
        plannable = self._validate()
        self._check_locks()
        self._check_cluster(plannable)
        free = self._free_spans()
        results: list[TaskResult] = []
        unscheduled: list[Unscheduled] = []

        for task, reserved, fixed in plannable:
            need = max(0, reserved - fixed)
            due = task.due_at.astimezone(self.zone)  # type: ignore[union-attr]
            soft_limit = due - timedelta(minutes=self.s.target_buffer_minutes)
            placed = self._place(task.id, need, free, soft_limit) if need else 0
            if placed < need:
                placed += self._place(task.id, need - placed, free, due)
            missing = need - placed
            results.append(TaskResult(task_id=task.id, estimated_minutes=task.remaining_minutes, reserved_minutes=reserved,
                                      locked_future_minutes=fixed, scheduled_minutes=placed, unscheduled_minutes=missing))
            if missing:
                reason = "deadline has passed" if due <= self.now else "not enough free time before the deadline"
                unscheduled.append(Unscheduled(task_id=task.id, minutes=missing, reason=reason))
                self.warnings.append(PlanWarning(code=INSUFFICIENT_TIME, task_id=task.id,
                                                 message=f"{task.title}: {missing / 60:g} h could not be planned ({reason})"))
            self._check_buffer(task, due)

        self.new_blocks.sort(key=lambda b: b.start)
        has_input_issue = any(w.code in (MISSING_DUE_AT, UNCONFIRMED_TASK) for w in self.warnings)
        if any(w.code == LOCK_CONFLICT for w in self.warnings):
            status = "blocked"
        elif unscheduled:
            status = "partial"
        elif not plannable and has_input_issue:
            status = "needs_input"
        else:
            status = "complete"
        return PlanResult(status=status, blocks=self.new_blocks, unscheduled=unscheduled, warnings=self.warnings,
                          task_results=results, retained_locked_blocks=list(self.req.locked_blocks))

    # -- steps ----------------------------------------------------------------------------------
    def _validate(self) -> list[tuple[PlanTask, int, int]]:
        out = []
        for t in self.req.tasks:
            if t.due_at is None:
                self.warnings.append(PlanWarning(code=MISSING_DUE_AT, task_id=t.id, message=f"{t.title}: no exact deadline yet"))
            if not t.confirmed:
                self.warnings.append(PlanWarning(code=UNCONFIRMED_TASK, task_id=t.id, message=f"{t.title}: not confirmed yet"))
            if t.due_at is None or not t.confirmed:
                continue
            if t.due_at.astimezone(self.zone) <= self.now:
                self.warnings.append(PlanWarning(code=PAST_DEADLINE, task_id=t.id, message=f"{t.title}: the deadline has passed"))
            reserved = round_up(t.remaining_minutes, self.step)
            fixed = sum(_minutes(b.start, b.end) for b in self.req.locked_blocks if b.task_id == t.id)
            out.append((t, reserved, fixed))
        out.sort(key=lambda x: (x[0].due_at, PRIORITY_RANK.get(x[0].priority, 1), x[0].id))
        return out

    def _check_locks(self) -> None:
        for lb in self.req.locked_blocks:
            for busy in self.req.busy:
                if lb.start < busy.end and busy.start < lb.end:
                    self.warnings.append(PlanWarning(code=LOCK_CONFLICT, task_id=lb.task_id,
                                                     message="a locked session now overlaps a class or meeting; move or unlock it"))
                    break

    def _check_cluster(self, plannable) -> None:
        dues = sorted((t.due_at, t.id) for t, _, _ in plannable)
        for i in range(len(dues)):
            window = [tid for d, tid in dues if dues[i][0] <= d <= dues[i][0] + timedelta(hours=48)]
            if len(window) >= 3:
                self.warnings.append(PlanWarning(code=DEADLINE_CLUSTER,
                                                 message=f"{len(window)} deadlines fall within 48 hours; start early"))
                return

    def _free_spans(self) -> list[Span]:
        """Available hours inside the daily study window, minus the past, classes, meetings and existing blocks."""
        spans: list[Span] = []
        start_t, end_t = time.fromisoformat(self.s.study_day_start), time.fromisoformat(self.s.study_day_end)
        for window in self.req.availability:
            a, b = window.start.astimezone(self.zone), window.end.astimezone(self.zone)
            day = a.date()
            while datetime.combine(day, time(0), self.zone) < b:
                lo = max(a, datetime.combine(day, start_t, self.zone), self.now)
                hi = min(b, datetime.combine(day, end_t, self.zone))
                lo, hi = _ceil(lo, self.step), _floor(hi, self.step)
                if hi > lo:
                    spans.append((lo, hi))
                day += timedelta(days=1)
        for busy in [*self.req.busy, *[Interval(start=a, end=b) for a, b in self.existing]]:
            cut = (_floor(busy.start.astimezone(self.zone), self.step), _ceil(busy.end.astimezone(self.zone), self.step))
            spans = _subtract(spans, cut)
        return sorted(s for s in spans if s[1] > s[0])

    def _place(self, task_id: str, need: int, free: list[Span], limit: datetime) -> int:
        """Fill earliest free time before `limit` with blocks of 30-90 minutes. Returns minutes placed."""
        placed = 0
        i = 0
        while placed < need and i < len(free):
            a, b = free[i]
            if a >= limit:
                break
            hi = min(b, limit)
            start = a
            made = False
            while start < hi and placed < need:
                length = self._fit(start, hi, need - placed)
                if length:
                    end = start + timedelta(minutes=length)
                    self.new_blocks.append(PlanBlock(task_id=task_id, start=start, end=end))
                    self.daily[start.date()] += length
                    placed += length
                    # availability entries may overlap: take these minutes out of every one of them
                    free[:] = sorted(piece for span in free for piece in _subtract([span], (start, end)))
                    i = 0
                    made = True
                    break
                start += timedelta(minutes=self.step)
            if not made:
                i += 1
        return placed

    def _fit(self, start: datetime, hi: datetime, left: int) -> int:
        """Longest legal block starting at `start` (0 if none)."""
        s = self.s
        room = _minutes(start, hi)
        cap = s.max_study_minutes_per_day - self.daily[start.date()]
        longest = min(s.max_block_minutes, room, cap, round_up(left, self.step))
        shortest = min(s.min_block_minutes, round_up(left, self.step))
        length = longest - longest % self.step
        while length >= shortest and length > 0:
            if self._continuity_ok(start, start + timedelta(minutes=length)):
                return length
            length -= self.step
        return 0

    def _continuity_ok(self, a: datetime, b: datetime) -> bool:
        """No run of study longer than max_block_minutes without a break of min_break_minutes (member 4's check)."""
        day = a.date()
        spans = sorted([*(x for x in self.existing if x[0].date() == day),
                        *((blk.start, blk.end) for blk in self.new_blocks if blk.start.date() == day), (a, b)])
        running, last_end = 0, None
        for x, y in spans:
            if last_end is None or _minutes(last_end, x) >= self.s.min_break_minutes:
                running = 0
            running += _minutes(x, y)
            if running > self.s.max_block_minutes:
                return False
            last_end = y
        return True

    def _check_buffer(self, task: PlanTask, due: datetime) -> None:
        ends = [blk.end for blk in self.new_blocks if blk.task_id == task.id]
        ends += [lb.end for lb in self.req.locked_blocks if lb.task_id == task.id]
        if not ends:
            return
        buffer = _minutes(max(ends), due)
        if buffer < self.s.target_buffer_minutes:
            self.warnings.append(PlanWarning(code=LOW_BUFFER, task_id=task.id,
                                             message=f"{task.title}: finishes {buffer / 60:.0f} h before the deadline"))


def generate(request: PlanRequest) -> PlanResult:
    return Planner(request).run()
