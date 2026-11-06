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
    task_cap: int = 0  # most minutes ONE task may get on one day (0 = no separate limit; the daily cap still applies)

    def task_room(self, done: int) -> int:
        """Minutes one task may still get on a day where it already has `done`."""
        return max(0, self.task_cap - done) if self.task_cap else 10 ** 6


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
         completed_by_day: dict[date, int], kept: list[dict] | None = None,
         committed_by_day: dict[date, int] | None = None,
         task_done: dict[tuple[str, date], int] | None = None) -> Result:
    """completed_by_day: minutes already logged that day on any task. committed_by_day: minutes of study blocks
    already written for that day but outside the horizon (e.g. later this hour) - they use the cap too.
    task_done: the same two, per (task id, day), for the per-task daily cap (p.task_cap).

    Tasks are placed in deadline order. Each task first gets the simple greedy layout (target-length sessions,
    earliest first); only if that leaves work unplaced is the task's layout searched exhaustively for the most
    minutes the rules allow. A plan where greedy places everything is therefore unchanged. As a guard the result
    is never worse in total than the plain greedy plan."""
    best = _plan(tasks, busy, p, t0, t1, completed_by_day, kept, committed_by_day, exact=True, task_done=task_done)
    if best.unmet > 0:
        plain = _plan(tasks, busy, p, t0, t1, completed_by_day, kept, committed_by_day, exact=False, task_done=task_done)
        if plain.unmet < best.unmet:
            best = plain
    if best.unmet > 0 and len(tasks) > 1 and not best.infeasible_proven:
        # Several tasks compete for the same days: a different placement order can make everything fit
        # (e.g. a 15-minute task leaving an unusable 25-minute scrap of a day's cap). If some order fits all work,
        # use it; if none does, keep the deadline-order result so urgent tasks keep priority.
        for order in _alternative_orders(tasks, p):
            cand = _plan(tasks, busy, p, t0, t1, completed_by_day, kept, committed_by_day, exact=True, order=order,
                         task_done=task_done)
            if cand.unmet == 0 and not cand.violations:
                cand.binding.append("placement_order_changed_to_fit_all_work")
                return cand
    return best


def _alternative_orders(tasks: list[TaskIn], p: Prefs, limit: int = 120) -> list[list[str]]:
    """Placement orders other than earliest-deadline-first, closest to it first. All orders for up to five tasks;
    a few targeted ones beyond that. Each task still has to finish before its own deadline buffer."""
    from itertools import islice, permutations
    edf = [t.id for t in sorted(tasks, key=lambda t: (t.cutoff, t.title))]
    if len(edf) <= 5:
        return [list(o) for o in islice(permutations(edf), 1, limit + 1)]
    by_id = {t.id: t for t in tasks}
    small_last = [i for i in edf if by_id[i].remaining >= p.s_min] + [i for i in edf if by_id[i].remaining < p.s_min]
    largest_first = [t.id for t in sorted(tasks, key=lambda t: (-t.remaining, t.cutoff, t.title))]
    return [o for o in (small_last, largest_first, list(reversed(edf))) if o != edf]


def _plan(tasks: list[TaskIn], busy: list[Interval], p: Prefs, t0: datetime, t1: datetime,
          completed_by_day: dict[date, int], kept: list[dict] | None, committed_by_day: dict[date, int] | None,
          exact: bool, order: list[str] | None = None,
          task_done: dict[tuple[str, date], int] | None = None) -> Result:
    tz = ZoneInfo(p.tz)
    r = Result()
    kept = kept or []
    committed_by_day = committed_by_day or {}
    task_done = task_done or {}
    tday: dict[tuple[str, date], int] = dict(task_done)  # per (task, day): logged + committed + fixed blocks
    windows = day_windows(p, t0, t1)
    free: dict[date, list[Interval]] = {}
    for d, w in windows.items():
        f = [w]
        for b in busy:
            f = _subtract(f, b)
        free[d] = f
    used = {d: completed_by_day.get(d, 0) + committed_by_day.get(d, 0) for d in windows}
    sessions: list[dict] = []
    for k in kept:
        # Fixed blocks: already-written study blocks ("kept", never written again) and pinned blocks (a suggestion
        # the student keeps in place or edited by hand - fixed here, still written when the plan is saved).
        # Both occupy time and count toward the cap and the task's work.
        d = k["start"].astimezone(tz).date()
        if d in free:
            free[d] = _subtract(free[d], (k["start"] - timedelta(minutes=p.brk), k["end"] + timedelta(minutes=p.brk)))
            used[d] = used.get(d, 0) + _mins(k["start"], k["end"])
        tday[(k["task_id"], d)] = tday.get((k["task_id"], d), 0) + _mins(k["start"], k["end"])
        sessions.append({**k, "kept": not k.get("pinned")})

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
    kept_by_task: dict[str, int] = {}  # written + pinned minutes: already covered, not placed again
    pinned_by_task: dict[str, int] = {}
    for k in kept:
        kept_by_task[k["task_id"]] = kept_by_task.get(k["task_id"], 0) + _mins(k["start"], k["end"])
        if k.get("pinned"):
            pinned_by_task[k["task_id"]] = pinned_by_task.get(k["task_id"], 0) + _mins(k["start"], k["end"])
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
    if p.task_cap:
        # The same bound for each task on its own, with its per-day limit: proves "this task alone cannot fit".
        for t in ordered:
            need = max(0, t.remaining - kept_by_task.get(t.id, 0))
            limit = t.cutoff - timedelta(minutes=p.buffer)
            own = loose = 0
            for d, f in free.items():
                mins = sum(max(0, _mins(s, min(e, limit))) for s, e in f if s < limit)
                day_room = min(max(0, p.daily_cap - used[d]), mins)
                loose += day_room
                own += min(day_room, p.task_room(tday.get((t.id, d), 0)))
            if need > own:
                r.infeasible_proven = True
                if need <= loose:  # it is the per-task limit, not the day or the calendar, that makes it impossible
                    r.binding.append(f"task_daily_cap:{t.id}:{need}:{own}")

    flex_iv = [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"])) for f in r.flex]
    by_id = {t.id: t for t in tasks}
    placement = [by_id[i] for i in order] if order else ordered
    for t in placement:
        remaining = max(0, t.remaining - kept_by_task.get(t.id, 0))
        limit = t.cutoff - timedelta(minutes=p.buffer)
        mine_day = {d: tday.get((t.id, d), 0) for d in windows}
        mine, left, free2, used2 = _place_greedy(t, remaining, limit, free, used, windows, busy, flex_iv, sessions, p, tz,
                                                 mine_day)
        method = "greedy"
        if left > 0 and exact:
            # Greedy left work unplaced: search all session layouts for this task and keep the best one.
            e_mine, e_left, e_free, e_used = _place_exact(t, remaining, limit, free, used, p, tz, mine_day)
            if e_left < left:
                mine, left, free2, used2, method = e_mine, e_left, e_free, e_used, "optimised"
        free, used = free2, used2
        sessions += mine
        r.per_task.append({"task_id": t.id, "title": t.title, "remaining": t.remaining,
                           "kept": kept_by_task.get(t.id, 0) - pinned_by_task.get(t.id, 0),
                           "planned": sum(x["minutes"] for x in mine) + pinned_by_task.get(t.id, 0),
                           "unmet": left, "cutoff": t.cutoff.isoformat(), "planning_limit": limit.isoformat(),
                           "placement": method})
        r.unmet += left
    rank = {t.id: i for i, t in enumerate(ordered)}
    r.per_task.sort(key=lambda x: rank[x["task_id"]])  # always reported in deadline order

    sessions.sort(key=lambda x: x["start"])
    # Emit every instant in the display zone so clients never compare mixed offsets as strings.
    r.sessions = [{**x, "start": x["start"].astimezone(tz).isoformat(), "end": x["end"].astimezone(tz).isoformat()}
                  for x in sessions]
    r.flex = [{**f, "start": datetime.fromisoformat(f["start"]).astimezone(tz).isoformat(),
               "end": datetime.fromisoformat(f["end"]).astimezone(tz).isoformat()} for f in r.flex]
    r.days = [{"date": d.isoformat(), "completed": completed_by_day.get(d, 0),
               "committed": committed_by_day.get(d, 0),
               "planned": sum(x["minutes"] for x in sessions if x["start"].astimezone(tz).date() == d),
               "cap": p.daily_cap} for d in sorted(windows)]
    r.violations = validate(r.sessions, r.flex, tasks, busy, p, t0, t1, completed_by_day, committed_by_day, task_done)
    return r


def _place_greedy(t: TaskIn, remaining: int, limit: datetime, free: dict, used: dict, windows: dict,
                  busy: list[Interval], flex_iv: list[Interval], placed: list[dict], p: Prefs, tz: ZoneInfo,
                  mine_day: dict | None = None):
    """Original layout: target-length sessions, earliest free time first. Works on copies of free/used.
    mine_day: minutes this task already has per day (for the per-task daily cap)."""
    free = {d: list(v) for d, v in free.items()}
    used = dict(used)
    mine_day = dict(mine_day or {})
    whole_small = 0 < remaining < p.s_min
    mine: list[dict] = []
    for d in sorted(free):
        if remaining <= 0:
            break
        pos = None  # free time before pos on this day has been considered
        while remaining > 0:
            # Re-read the day's free time each round: a session just placed removes its break padding, which can
            # reach into the next interval (e.g. past a meeting shorter than the break).
            nxt = [(s if pos is None else max(s, pos), e) for s, e in free[d] if pos is None or e > pos]
            nxt = [(s, e) for s, e in nxt if s < e]
            if not nxt:
                break
            s, e_full = nxt[0]
            pos = e_full
            e = min(e_full, limit)
            while remaining > 0 and s < e:
                allowance = min(p.daily_cap - used[d], p.s_max, p.task_room(mine_day.get(d, 0)))
                length = min(p.s_target, remaining, allowance, _mins(s, e))
                if remaining - length > 0 and remaining - length < p.s_min and length + (remaining - length) <= min(p.s_max, allowance, _mins(s, e)):
                    length = remaining  # absorb a would-be short tail into this session
                ok_short = whole_small and length == remaining
                if length < p.s_min and not ok_short:
                    break
                block = (s, s + timedelta(minutes=length))
                mine.append({"task_id": t.id, "task_title": t.title, "phase": "study", "start": block[0], "end": block[1],
                             "minutes": length})
                used[d] += length
                mine_day[d] = mine_day.get(d, 0) + length
                remaining -= length
                free[d] = _subtract(free[d], (block[0] - timedelta(minutes=p.brk), block[1] + timedelta(minutes=p.brk)))
                s = block[1] + timedelta(minutes=p.brk)
            if remaining <= 0:
                break
    if 0 < remaining < p.s_min and mine:
        # Final fragment shorter than the minimum: extend an earlier legal session or report it.
        for sess in reversed(mine):
            d = sess["start"].astimezone(tz).date()
            ext = (sess["end"], sess["end"] + timedelta(minutes=remaining))
            others = [(o["start"] - timedelta(minutes=p.brk), o["end"] + timedelta(minutes=p.brk))
                      for o in placed + mine if o is not sess]
            clear = all(not (ext[0] < be and bs < ext[1]) for bs, be in busy + flex_iv + others)
            if (clear and ext[1] <= windows[d][1] and sess["minutes"] + remaining <= p.s_max
                    and used[d] + remaining <= p.daily_cap and remaining <= p.task_room(mine_day.get(d, 0))
                    and ext[1] <= limit):
                sess["end"], sess["minutes"] = ext[1], sess["minutes"] + remaining
                used[d] += remaining
                mine_day[d] = mine_day.get(d, 0) + remaining
                free[d] = _subtract(free[d], (ext[0], ext[1] + timedelta(minutes=p.brk)))
                remaining = 0
                break
    return mine, remaining, free, used


def _grid(values: list[int]) -> int:
    """Largest step (at most 5 minutes) that divides every quantity; 1 minute when times are irregular."""
    from math import gcd
    g = 0
    for v in values:
        g = gcd(g, abs(int(v)))
    return g if g in (1, 5) else (5 if g and g % 5 == 0 else 1)


def _place_exact(t: TaskIn, remaining: int, limit: datetime, free: dict, used: dict, p: Prefs, tz: ZoneInfo,
                 mine_day: dict | None = None):
    """Most minutes this task can get under the rules: sessions of s_min..s_max minutes (one shorter session only
    when the whole remainder is below s_min), a break between sessions, the daily cap and the per-task daily cap,
    free time only, nothing after the planning limit. Exact search: per day, the earliest finishing layout for every achievable total;
    across days, the best combination (earlier days filled first). Works on copies of free/used."""
    free = {d: list(v) for d, v in free.items()}
    used = dict(used)
    days = sorted(free)
    origin = min((iv[0] for d in days for iv in free[d]), default=None)
    if origin is None or remaining <= 0:
        return [], remaining, free, used
    off = lambda x: _mins(origin, x)  # noqa: E731 - minutes since the first free instant
    per_day = {}
    for d in days:
        ivs = [(off(s), off(min(e, limit))) for s, e in free[d] if s < limit and min(e, limit) > s]
        per_day[d] = (ivs, min(max(0, p.daily_cap - used[d]), p.task_room((mine_day or {}).get(d, 0))))
    g = _grid([remaining, p.s_min, p.s_max, p.brk, p.daily_cap]
              + [x for ivs, room in per_day.values() for iv in ivs for x in iv] + [room for _, room in per_day.values()])
    if 0 < remaining < p.s_min:
        lengths = [remaining]  # the whole remainder may be one short session
    else:
        lengths = sorted(range(p.s_min, p.s_max + 1, g), key=lambda x: (abs(x - p.s_target), x))

    def fit(start: int, length: int, ivs) -> int | None:
        for a, b in ivs:
            s0 = max(start, a)
            if s0 + length <= b:
                return s0
        return None

    layouts = {}
    for d, (ivs, room) in per_day.items():
        top = min(room, remaining)
        # total -> (end, deviation from target length, previous total, start, length).
        reach: dict[int, tuple] = {0: (None, 0, None, None, None)}
        for total in range(0, top + 1, g):
            if total not in reach:
                continue
            end, dev = reach[total][0], reach[total][1]
            earliest = ivs[0][0] if ivs and end is None else (end + p.brk if end is not None else 0)
            for length in lengths:
                nxt = total + length
                if nxt > top:
                    continue
                a = fit(earliest, length, ivs)
                if a is None:
                    continue
                cand = (a + length, dev + abs(length - p.s_target), total, a, length)
                # Ties: earliest end, then closest to the target length, then longer sessions first.
                if nxt not in reach or (cand[0], cand[1], -cand[2]) < (reach[nxt][0], reach[nxt][1], -reach[nxt][2]):
                    reach[nxt] = cand
        layouts[d] = reach

    # Choose one achievable total per day, as many minutes as possible overall, earlier days first.
    suffix = [0] * (len(days) + 1)  # most minutes days[i:] can hold, each day independently at its maximum
    for i in range(len(days) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + max(layouts[days[i]])
    memo: dict[tuple[int, int], int] = {}

    def best(i: int, budget: int) -> int:
        if i == len(days) or budget <= 0:
            return 0
        if budget >= suffix[i]:
            return suffix[i]  # enough work to fill every remaining day to its maximum
        key = (i, budget)
        if key not in memo:
            memo[key] = max(x + best(i + 1, budget - x) for x in layouts[days[i]] if x <= budget)
        return memo[key]

    target = best(0, remaining)
    mine: list[dict] = []
    budget = remaining
    for i, d in enumerate(days):
        want = best(i, budget)
        choice = max(x for x in layouts[d] if x <= budget and x + best(i + 1, budget - x) == want)
        budget -= choice
        reach, total, blocks = layouts[d], choice, []
        while total:
            _, _, prev, a, length = reach[total]
            blocks.append((a, length))
            total = prev
        for a, length in sorted(blocks):
            st = origin + timedelta(minutes=a)
            en = st + timedelta(minutes=length)
            mine.append({"task_id": t.id, "task_title": t.title, "phase": "study", "start": st, "end": en,
                         "minutes": length})
            used[d] += length
            free[d] = _subtract(free[d], (st - timedelta(minutes=p.brk), en + timedelta(minutes=p.brk)))
    return mine, remaining - target, free, used


def validate(sessions: list[dict], flex: list[dict], tasks: list[TaskIn], busy: list[Interval], p: Prefs,
             t0: datetime, t1: datetime, completed_by_day: dict[date, int],
             committed_by_day: dict[date, int] | None = None,
             task_done: dict[tuple[str, date], int] | None = None) -> list[str]:
    """Re-check every hard constraint from scratch; returns human-readable violations."""
    tz = ZoneInfo(p.tz)
    v: list[str] = []
    by_task = {t.id: t for t in tasks}
    parsed = sorted(((datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]), s) for s in sessions),
                    key=lambda x: x[0])
    flex_iv = [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"])) for f in flex]
    per_day: dict[date, int] = {}
    per_task_day: dict[tuple[str, date], int] = {}
    new_on: set[tuple[str, date]] = set()
    # A remainder below the minimum may be one short session. "Remainder" is what is left after already-written
    # (kept) blocks and the other held-in-place (pinned) blocks, exactly as the planner computes it - otherwise a
    # legal short session is rejected.
    kept_by_task: dict[str, int] = {}
    pinned_by_task: dict[str, int] = {}
    for x in sessions:
        bucket = kept_by_task if x.get("kept") else pinned_by_task if x.get("pinned") else None
        if bucket is not None:
            bucket[x["task_id"]] = bucket.get(x["task_id"], 0) + x["minutes"]

    def small_ok(x: dict) -> bool:
        t = by_task.get(x["task_id"])
        if t is None:
            return False
        held = kept_by_task.get(t.id, 0) + pinned_by_task.get(t.id, 0) - (x["minutes"] if x.get("pinned") else 0)
        return 0 < t.remaining - held < p.s_min
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
        if not x.get("kept") and (x["minutes"] > p.s_max or (x["minutes"] < p.s_min and not small_ok(x))):
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
        key = (x["task_id"], ls.date())
        per_task_day[key] = per_task_day.get(key, 0) + x["minutes"]
        if not x.get("kept"):
            new_on.add(key)
    committed_by_day = committed_by_day or {}
    for d, m in per_day.items():
        if m + completed_by_day.get(d, 0) + committed_by_day.get(d, 0) > p.daily_cap:
            v.append(f"daily_cap_exceeded:{d.isoformat()}")
    if p.task_cap:
        # Only a day this plan adds to: blocks already written are facts, not something this plan can fix.
        for (tid, d), m in sorted(per_task_day.items()):
            if (tid, d) in new_on and m + (task_done or {}).get((tid, d), 0) > p.task_cap:
                v.append(f"task_daily_cap_exceeded:{tid}@{d.isoformat()}")
    return v


def plan_status(result: Result, missing: list[str], has_tasks: bool, snapshot_ok: bool,
                overrides: list[str] | None = None) -> str:
    """The one place that turns a planner result into a plan status. `overrides` are rule exceptions the student
    explicitly accepted for hand-edited blocks; they no longer block the plan."""
    if not snapshot_ok:
        return "needs_information"
    if [v for v in result.violations if v not in (overrides or [])]:
        return "needs_adjustment"
    if missing and not has_tasks:
        return "needs_information"
    if result.unmet == 0:
        return "feasible" if not missing else "needs_information"
    return "infeasible" if result.infeasible_proven else "needs_adjustment"
