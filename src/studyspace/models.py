"""Shared data objects. Modules exchange only these objects; change them only with the team's agreement.

Formats used everywhere:
- times are ISO 8601 with an offset (e.g. 2026-09-30T23:59:00+08:00), time zone Asia/Singapore
- effort is always in minutes
- an uncertain date stays empty and carries a warning code; it is never filled in as 23:59
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

# ---- warning / flag codes -------------------------------------------------------------------
NEEDS_CONFIRM = "NEEDS_CONFIRM"            # date inferred (relative, week-based) or time missing
MISSING_DUE_AT = "MISSING_DUE_AT"          # the message gives no deadline at all
MIDNIGHT_AMBIGUITY = "MIDNIGHT_AMBIGUITY"  # "12 midnight Sept 28": start or end of the day?
DATE_CHANGED = "DATE_CHANGED"              # a newer message moves an existing deadline
UNCONFIRMED_TASK = "UNCONFIRMED_TASK"
INSUFFICIENT_TIME = "INSUFFICIENT_TIME"
LOW_BUFFER = "LOW_BUFFER"
LOCK_CONFLICT = "LOCK_CONFLICT"
PAST_DEADLINE = "PAST_DEADLINE"
STALE_DRAFT = "STALE_DRAFT"
DEADLINE_CLUSTER = "DEADLINE_CLUSTER"
SENSITIVE_RECIPIENT = "SENSITIVE_RECIPIENT"

SourceType = Literal["csv", "eml", "paste", "teams", "pdf", "synthetic"]
TaskKind = Literal["deliverable", "event"]
Priority = Literal["high", "medium", "low"]


class Source(BaseModel):
    """One email, chat thread or file, kept exactly as received."""

    record_id: str
    source_type: SourceType
    course_code: str | None = None
    subject: str | None = None
    sender: str | None = None
    received_at: AwareDatetime | None = None
    body_text: str
    meta: dict[str, Any] = Field(default_factory=dict)


class Candidate(BaseModel):
    """A task proposed by extraction. It becomes a Task only after the student confirms it (gate 1)."""

    candidate_id: str
    source_ids: list[str]
    title: str
    course_code: str | None = None
    kind: TaskKind = "deliverable"
    due_text: str | None = None          # the deadline as written in the message
    due_date: date | None = None         # known day, even when the time is not
    due_at: AwareDatetime | None = None  # only when both day and time are known
    due_options: list[AwareDatetime] = Field(default_factory=list)  # readings the student must choose from
    evidence: str                        # the sentence the task came from
    flags: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)  # earlier mentions: source_id, due_text, due_at
    related_task_id: str | None = None   # set when the candidate updates an existing task
    status: Literal["pending", "confirmed", "dismissed"] = "pending"


class Task(BaseModel):
    """A task the student has confirmed. Only confirmed tasks are scheduled."""

    task_id: str
    title: str
    course_code: str | None = None
    kind: TaskKind = "deliverable"
    due_at: AwareDatetime
    remaining_minutes: int = Field(ge=0)
    priority: Priority = "medium"
    confirmed: bool = True
    status: Literal["open", "done"] = "open"
    source_ids: list[str] = Field(default_factory=list)


class Interval(BaseModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> "Interval":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class TimeSlot(Interval):
    kind: Literal["available", "busy"]
    label: str | None = None
    origin: Literal["manual", "ics", "synthetic"] = "manual"
    slot_id: str | None = None  # assigned when stored


# ---- planning: field names follow member 4's reference cases ---------------------------------
class PlanSettings(BaseModel):
    study_day_start: str = "09:00"
    study_day_end: str = "22:00"
    max_study_minutes_per_day: int = 180
    min_block_minutes: int = 30
    max_block_minutes: int = 90
    min_break_minutes: int = 15
    time_step_minutes: int = 15
    target_buffer_minutes: int = 1440


class PlanTask(BaseModel):
    id: str
    title: str
    due_at: AwareDatetime | None
    remaining_minutes: int
    priority: Priority = "medium"
    confirmed: bool = True


class PlanBlock(Interval):
    task_id: str


class PlanRequest(BaseModel):
    now: AwareDatetime
    timezone: str = "Asia/Singapore"
    tasks: list[PlanTask]
    availability: list[Interval]
    busy: list[Interval] = Field(default_factory=list)
    completed_blocks: list[PlanBlock] = Field(default_factory=list)
    locked_blocks: list[PlanBlock] = Field(default_factory=list)
    settings: PlanSettings = Field(default_factory=PlanSettings)


class Unscheduled(BaseModel):
    task_id: str
    minutes: int
    reason: str | None = None


class PlanWarning(BaseModel):
    code: str
    task_id: str | None = None
    message: str = ""


class TaskResult(BaseModel):
    task_id: str
    estimated_minutes: int
    reserved_minutes: int
    locked_future_minutes: int
    scheduled_minutes: int
    unscheduled_minutes: int


class PlanResult(BaseModel):
    status: Literal["complete", "partial", "needs_input", "blocked"]
    blocks: list[PlanBlock] = Field(default_factory=list)
    unscheduled: list[Unscheduled] = Field(default_factory=list)
    warnings: list[PlanWarning] = Field(default_factory=list)
    task_results: list[TaskResult] = Field(default_factory=list)
    retained_locked_blocks: list[PlanBlock] = Field(default_factory=list)


class Progress(BaseModel):
    """Work the student marked as done. op_id makes repeated submissions harmless."""

    op_id: str
    task_id: str
    start: AwareDatetime
    end: AwareDatetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)
