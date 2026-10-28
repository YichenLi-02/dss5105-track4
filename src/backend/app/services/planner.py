"""Deterministic earliest-deadline-first planner + an independent validator (design 01 §6).

Never loosens a limit to make a plan fit: unplaced minutes are reported as a gap.
'infeasible' is claimed only when an upper bound on capacity before a cutoff is already
below the demand due by then; otherwise an incomplete heuristic result is 'needs_adjustment'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Interval = tuple[datetime, datetime]


@dataclass
class TaskIn:
    id: str
    title: str
    remaining: int
    cutoff: datetime  # aware


@dataclass
class Prefs:
    tz: str
    day_start: str
    day_end: str
    daily_cap: int
    s_min: int
    s_target: int
    s_max: int
    brk: int
    buffer: int
    flex: int


@dataclass
class Result:
    sessions: list[dict] = field(default_factory=list)
    flex: list[dict] = field(default_factory=list)
    per_task: list[dict] = field(default_factory=list)
    unmet: int = 0
    demand: int = 0
    capacity_upper_bound: int | None = None
    infeasible_proven: bool = False
    binding: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    days: list[dict] = field(default_factory=list)


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _subtract(free: list[Interval], block: Interval) -> list[Interval]:
    out = []
    bs, be = block
    for s, e in free:
        if be <= s or bs >= e:
            out.append((s, e))
            continue
        if bs > s:
            out.append((s, bs))
        if be < e:
            out.append((be, e))
    return out


def _mins(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def day_windows(p: Prefs, t0: datetime, t1: datetime) -> dict[date, Interval]:
    tz = ZoneInfo(p.tz)
    d, end = t0.astimezone(tz).date(), t1.astimezone(tz).date()
    out = {}
    while d <= end:
        s = max(datetime.combine(d, _hm(p.day_start), tz), t0)
        e = min(datetime.combine(d, _hm(p.day_end), tz), t1)
        if e > s:
            out[d] = (s, e)
        d += timedelta(days=1)
    return out


def plan(tasks: list[TaskIn], busy: list[Interval], p: Prefs, t0: datetime, t1: datetime,
         completed_by_day: dict[date, int], kept: list[dict] | None = None) -> Result:
    tz = ZoneInfo(p.tz)
    r = Result()
    kept = kept or []
    windows = day_windows(p, t0, t1)
    free: dict[date, list[Interval]] = {}
    for d, w in windows.items():
        f = [w]
        for b in busy:
            f = _subtract(f, b)
        free[d] = f
    used = {d: completed_by_day.get(d, 0) for d in windows}
    sessions: list[dict] = []
    for k in kept:  # already-written own study blocks: fixed, count toward cap, not "completed"
        d = k["start"].astimezone(tz).date()
        if d in free:
            free[d] = _subtract(free[d], (k["start"] - timedelta(minutes=p.brk), k["end"] + timedelta(minutes=p.brk)))
            used[d] = used.get(d, 0) + _mins(k["start"], k["end"])
        sessions.append({**k, "kept": True})

    # Weekly flexible time: reserved deterministically from the latest useful free slots of each ISO week.
    latest_limit = max((t.cutoff - timedelta(minutes=p.buffer) for t in tasks), default=t1)
    by_week: dict[tuple[int, int], list[date]] = {}
    for d in sorted(windows):
        by_week.setdefault(d.isocalendar()[:2], []).append(d)
    for week_days in by_week.values():
        need = p.flex
        for d in reversed(week_days):
            if need <= 0:
                break
            for s, e in reversed(list(free[d])):
                e2 = min(e, latest_limit)
                if need <= 0 or e2 <= s:
                    continue
                take = min(need, _mins(s, e2))
                block = (e2 - timedelta(minutes=take), e2)
                free[d] = _subtract(free[d], block)
                r.flex.append({"start": block[0].isoformat(), "end": block[1].isoformat(), "kind": "reserved_flex",
                               "source_id": "weekly_flex"})
                need -= take
        if need > 0:
            r.binding.append(f"weekly_flex_short_by:{need}")

    ordered = sorted(tasks, key=lambda t: (t.cutoff, t.title))
    kept_by_task: dict[str, int] = {}
    for k in kept:
        kept_by_task[k["task_id"]] = kept_by_task.get(k["task_id"], 0) + _mins(k["start"], k["end"])
    r.demand = sum(max(0, t.remaining - kept_by_task.get(t.id, 0)) for t in tasks)

    # Upper bound per cutoff (ignores session granularity and breaks -> only an upper bound).
    cumulative = 0
    for t in ordered:
        cumulative += max(0, t.remaining - kept_by_task.get(t.id, 0))
        limit = t.cutoff - timedelta(minutes=p.buffer)
        cap = 0
        for d, f in free.items():
            mins = sum(max(0, _mins(s, min(e, limit))) for s, e in f if s < limit)
            cap += min(max(0, p.daily_cap - used[d]), mins)
        if t is ordered[-1]:
            r.capacity_upper_bound = cap
        if cumulative > cap:
            r.infeasible_proven = True
            r.binding.append(f"demand_{cumulative}_exceeds_capacity_{cap}_before:{limit.isoformat()}")

    for t in ordered:
        remaining = max(0, t.remaining - kept_by_task.get(t.id, 0))
        whole_small = 0 < remaining < p.s_min
        limit = t.cutoff - timedelta(minutes=p.buffer)
        mine: list[dict] = []
        for d in sorted(free):
            if remaining <= 0:
                break
            for s, e in list(free[d]):
                e = min(e, limit)
                while remaining > 0 and s < e:
                    allowance = min(p.daily_cap - used[d], p.s_max)
                    length = min(p.s_target, remaining, allowance, _mins(s, e))
                    if remaining - length > 0 and remaining - length < p.s_min and length + (remaining - length) <= min(p.s_max, allowance, _mins(s, e)):
                        length = remaining  # absorb a would-be short tail into this session
                    ok_short = whole_small and length == remaining
                    if length < p.s_min and not ok_short:
                        break
                    block = (s, s + timedelta(minutes=length))
                    sess = {"task_id": t.id, "task_title": t.title, "phase": "study", "start": block[0], "end": block[1],
                            "minutes": length}
                    mine.append(sess)
                    used[d] += length
                    remaining -= length
                    free[d] = _subtract(free[d], (block[0] - timedelta(minutes=p.brk), block[1] + timedelta(minutes=p.brk)))
                    s = block[1] + timedelta(minutes=p.brk)
                if remaining <= 0:
                    break
        if 0 < remaining < p.s_min and mine:
            # Final fragment shorter than the minimum: extend an earlier legal session or report it.
            flex_iv = [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"])) for f in r.flex]
            for sess in reversed(mine):
                d = sess["start"].astimezone(tz).date()
                ext = (sess["end"], sess["end"] + timedelta(minutes=remaining))
                others = [(o["start"] - timedelta(minutes=p.brk), o["end"] + timedelta(minutes=p.brk))
                          for o in sessions + mine if o is not sess]
                clear = all(not (ext[0] < be and bs < ext[1]) for bs, be in busy + flex_iv + others)
                if (clear and ext[1] <= windows[d][1] and sess["minutes"] + remaining <= p.s_max
                        and used[d] + remaining <= p.daily_cap and ext[1] <= limit):
                    sess["end"], sess["minutes"] = ext[1], sess["minutes"] + remaining
                    used[d] += remaining
                    free[d] = _subtract(free[d], (ext[0], ext[1] + timedelta(minutes=p.brk)))
                    remaining = 0
                    break
        sessions += mine
        r.per_task.append({"task_id": t.id, "title": t.title, "remaining": t.remaining,
                           "kept": kept_by_task.get(t.id, 0), "planned": sum(x["minutes"] for x in mine),
                           "unmet": remaining, "cutoff": t.cutoff.isoformat(), "planning_limit": limit.isoformat()})
        r.unmet += remaining

    sessions.sort(key=lambda x: x["start"])
    # Emit every instant in the display zone so clients never compare mixed offsets as strings.
    r.sessions = [{**x, "start": x["start"].astimezone(tz).isoformat(), "end": x["end"].astimezone(tz).isoformat()}
                  for x in sessions]
    r.flex = [{**f, "start": datetime.fromisoformat(f["start"]).astimezone(tz).isoformat(),
               "end": datetime.fromisoformat(f["end"]).astimezone(tz).isoformat()} for f in r.flex]
    r.days = [{"date": d.isoformat(), "completed": completed_by_day.get(d, 0),
               "planned": sum(x["minutes"] for x in sessions if x["start"].astimezone(tz).date() == d),
               "cap": p.daily_cap} for d in sorted(windows)]
    r.violations = validate(r.sessions, r.flex, tasks, busy, p, t0, t1, completed_by_day)
    return r


def validate(sessions: list[dict], flex: list[dict], tasks: list[TaskIn], busy: list[Interval], p: Prefs,
             t0: datetime, t1: datetime, completed_by_day: dict[date, int]) -> list[str]:
    """Re-check every hard constraint from scratch; returns human-readable violations."""
    tz = ZoneInfo(p.tz)
    v: list[str] = []
    by_task = {t.id: t for t in tasks}
    parsed = sorted(((datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]), s) for s in sessions),
                    key=lambda x: x[0])
    flex_iv = [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"])) for f in flex]
    per_day: dict[date, int] = {}
    small_ok = {t.id for t in tasks if 0 < t.remaining < p.s_min}
    for i, (s, e, x) in enumerate(parsed):
        tag = f"{x['task_id']}@{s.isoformat()}"
        if not s < e:
            v.append(f"non_positive:{tag}")
        if _mins(s, e) != x["minutes"]:
            v.append(f"minutes_mismatch:{tag}")
        ls, le = s.astimezone(tz), e.astimezone(tz)
        if ls.date() != le.date() or ls.time() < _hm(p.day_start) or (le.time() > _hm(p.day_end) and le.time() != time(0)):
            v.append(f"outside_day_window:{tag}")
        if s < t0 or e > t1:
            v.append(f"outside_horizon:{tag}")
        if not x.get("kept") and (x["minutes"] > p.s_max or (x["minutes"] < p.s_min and x["task_id"] not in small_ok)):
            v.append(f"session_length:{tag}")
        for bs, be in busy + flex_iv:
            if s < be and bs < e:
                v.append(f"overlaps_busy_or_flex:{tag}")
                break
        t = by_task.get(x["task_id"])
        if t and not x.get("kept") and e > t.cutoff - timedelta(minutes=p.buffer):
            v.append(f"inside_deadline_buffer:{tag}")
        if i > 0:
            ps, pe, _ = parsed[i - 1]
            if s < pe + timedelta(minutes=p.brk):
                v.append(f"break_too_short:{tag}")
        per_day[ls.date()] = per_day.get(ls.date(), 0) + x["minutes"]
    for d, m in per_day.items():
        if m + completed_by_day.get(d, 0) > p.daily_cap:
            v.append(f"daily_cap_exceeded:{d.isoformat()}")
    return v
