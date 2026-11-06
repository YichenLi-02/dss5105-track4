"""Plan conflicts and repair options. Pure: works on planner inputs, no database, calendar or network.

A conflict is a study block that now overlaps busy time (for example a meeting added after the plan was made),
or work that no longer fits before its deadline. Each option re-runs the planner with different blocks held in
place, so the student sees concrete alternatives rather than one silent fix:

  shift        keep every block that is not in conflict; move only the affected work (fewest changes)
  use_flex     as shift, but the week's reserved flexible time may be used          (relaxes a rule)
  yield_later  tasks due later give up their suggested blocks to the affected task
  replan       plan everything again, keeping only blocks the student locked
  raise_cap    the best of the above with the daily cap and/or the per-task daily cap raised by 30 minutes
                                                                                    (relaxes a rule)

Options that keep every one of the student's rules come first, ranked by least unplaced work, fewest changed
blocks, most slack before the deadline. Options that relax a rule follow, labelled, and are shown only when they
place more work than every option before them; any option no better than a higher-ranked one is not shown. Already-written blocks in conflict are moved (old event removed, new one created) only when their
calendar event id is known; nothing is written until the student reviews and confirms the chosen plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import planner

MAX_OPTIONS = 3
CAP_STEP = 30


def _dt(x) -> datetime:
    return x if isinstance(x, datetime) else datetime.fromisoformat(x)


def _key(s: dict) -> tuple:
    return (s["task_id"], _dt(s["start"]), _dt(s["end"]))


def overlapping(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    return [(bs, be) for bs, be in busy if start < be and bs < end]


def find_conflicts(sessions: list[dict], busy: list[tuple[datetime, datetime]]) -> list[dict]:
    """Every block (suggested, locked or already written) that overlaps busy time."""
    out = []
    for s in sessions:
        hits = overlapping(_dt(s["start"]), _dt(s["end"]), busy)
        if hits:
            out.append({"task_id": s["task_id"], "task_title": s.get("task_title", ""),
                        "start": _dt(s["start"]).isoformat(), "end": _dt(s["end"]).isoformat(),
                        "written": bool(s.get("written") or s.get("kept")), "locked": bool(s.get("locked")),
                        "busy": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in hits]})
    return out


@dataclass
class Option:
    strategy: str
    result: planner.Result
    status: str
    changed: int  # blocks in this option that are new or moved compared with the current plan
    dropped: int  # blocks of the current plan that this option no longer has
    relaxed: list[str] = field(default_factory=list)
    remove_written: list[dict] = field(default_factory=list)  # written events this option moves (delete + recreate)
    min_slack_minutes: int | None = None
    prefs: planner.Prefs | None = None

    @property
    def rank(self) -> tuple:
        return (bool(self.relaxed), self.result.unmet, len(self.relaxed), self.changed, -(self.min_slack_minutes or 0))


def build_options(tasks: list[planner.TaskIn], busy: list[tuple[datetime, datetime]], prefs: planner.Prefs,
                  t0: datetime, t1: datetime, completed: dict, committed: dict, written: list[dict],
                  current: list[dict], overrides: list[str] | None = None,
                  task_done: dict | None = None) -> tuple[list[dict], list[Option]]:
    """written: verified, future, already-written blocks (datetimes; 'event_id' when known).
    current: the current plan's other future blocks (suggested or locked), datetimes.
    Returns (conflicts, ranked options). No options when nothing conflicts and all work fits."""
    overrides = overrides or []
    conflicts = find_conflicts([{**w, "written": True} for w in written] + current, busy)
    clash = {(c["task_id"], _dt(c["start"]), _dt(c["end"])) for c in conflicts}
    written_clash = [w for w in written if _key(w) in clash]
    planned_ids = {t.id for t in tasks}
    # Only a block whose task is in this plan can move: its work is placed again. A clashing block of a task that is
    # not being planned stays (and stays reported) rather than being deleted with nothing in its place.
    movable = [w for w in written_clash if w.get("event_id") and w["task_id"] in planned_ids]
    fixed_written = [w for w in written if w not in movable]  # includes clashing blocks we cannot move
    current_ok = [s for s in current if _key(s) not in clash]
    base_keys = {_key(s) for s in written + current}

    def run(pins: list[dict], p: planner.Prefs) -> planner.Result:
        fixed = [{k: v for k, v in w.items() if k != "written"} for w in fixed_written]
        return planner.plan(tasks, busy, p, t0, t1, completed, fixed + [{**s, "pinned": True} for s in pins], committed,
                            task_done)

    def make(strategy: str, pins: list[dict], p: planner.Prefs, relaxed: list[str]) -> Option:
        r = run(pins, p)
        keys = {_key(x) for x in r.sessions}
        slack = None
        for t in tasks:
            ends = [_dt(x["end"]) for x in r.sessions if x["task_id"] == t.id]
            if ends:
                m = int((t.cutoff - max(ends)).total_seconds() // 60)
                slack = m if slack is None else min(slack, m)
        return Option(strategy, r, planner.plan_status(r, [], bool(tasks), True, overrides), len(keys - base_keys),
                      len(base_keys - keys), relaxed, [{"event_id": w["event_id"], "task_id": w["task_id"],
                                                         "start": w["start"].isoformat(), "end": w["end"].isoformat()}
                                                        for w in movable], slack, p)

    current_unmet = run(current_ok + [], prefs).unmet if not conflicts else None
    if not conflicts and current_unmet == 0:
        return conflicts, []

    shift = make("shift", current_ok, prefs, [])
    lengths = [int((_dt(c["end"]) - _dt(c["start"])).total_seconds() // 60) for c in conflicts]
    whole = min(min(lengths, default=0), prefs.s_max)
    if whole > prefs.s_min:  # first try moving each affected block as one piece instead of splitting it
        w = make("shift", current_ok, replace(prefs, s_min=whole, s_target=max(prefs.s_target, whole)), [])
        if w.result.unmet == 0 and w.rank < shift.rank:  # stricter lengths only; the student's rules are unchanged
            w.prefs = prefs
            shift = w
    opts = [shift]
    if prefs.flex > 0:
        opts.append(make("use_flex", current_ok, replace(prefs, flex=0), ["weekly_flex_used"]))
    displaced = {c["task_id"] for c in conflicts}
    if displaced:
        due = min((t.cutoff for t in tasks if t.id in displaced), default=None)
        later = {t.id for t in tasks if due is not None and t.cutoff > due}
        yielding = [s for s in current_ok if s.get("locked") or s["task_id"] not in later]
        if len(yielding) != len(current_ok):
            opts.append(make("yield_later", yielding, prefs, []))
    opts.append(make("replan", [s for s in current_ok if s.get("locked")], prefs, []))
    if min(o.result.unmet for o in opts) > 0:
        # What a looser limit would buy: the day's cap, the per-task cap, or both (only shown if it places more).
        variants = [(replace(prefs, daily_cap=prefs.daily_cap + CAP_STEP), [f"daily_cap_plus:{CAP_STEP}"])]
        if prefs.task_cap:
            variants += [(replace(prefs, task_cap=prefs.task_cap + CAP_STEP), [f"task_cap_plus:{CAP_STEP}"]),
                         (replace(prefs, daily_cap=prefs.daily_cap + CAP_STEP, task_cap=prefs.task_cap + CAP_STEP),
                          [f"daily_cap_plus:{CAP_STEP}", f"task_cap_plus:{CAP_STEP}"])]
        for bigger, relaxed in variants:
            for base in ("shift", "replan"):
                pins = current_ok if base == "shift" else [s for s in current_ok if s.get("locked")]
                opts.append(make("raise_cap", pins, bigger, relaxed))

    ranked, seen = [], set()
    for o in sorted(opts, key=lambda o: o.rank):
        sig = frozenset(_key(x) for x in o.result.sessions)
        if sig in seen:
            continue  # same blocks as a better-ranked option
        if any(k.result.unmet <= o.result.unmet and set(k.relaxed) <= set(o.relaxed) and k.changed <= o.changed
               for k in ranked):
            continue  # no better than an option already listed in any way the student would care about
        seen.add(sig)
        ranked.append(o)
    return conflicts, ranked[:MAX_OPTIONS]


def edit_window_ok(start: datetime, end: datetime, t0: datetime, t1: datetime, now: datetime) -> list[str]:
    """Hard limits for a hand-edited block (soft rules are reported by the validator and can be accepted)."""
    errs = []
    if not start < end:
        errs.append("end_before_start")
    if start <= now:
        errs.append("starts_in_the_past")
    if start < t0 or end > t1:
        errs.append("outside_planning_window")
    if start.date() != (end - timedelta(seconds=1)).date():
        errs.append("crosses_midnight")
    return errs
