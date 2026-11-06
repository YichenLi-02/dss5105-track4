"""Repeatable evaluation of the study planner.

Two parts:
  * fixed scenarios (scenarios.json): inputs plus expected results written by hand from the rules, to be checked by
    the group. They are compared with what the planner produced.
  * seeded scenarios: N inputs generated from a fixed random seed. They have no hand-written expectations; they
    are scored on hard-rule violations and on how much of the demand was actually scheduled.

Every metric here is computed from the raw sessions, independently of planner.validate(), so the planner is not
grading itself. Zero violations alone is not success (an empty plan has none): coverage and unplaced minutes are
always reported next to them.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services import calibration, planner, repair
from app.services.plan_service import plan_status

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios.json"
DEFAULT_PREFS = {"tz": "Asia/Singapore", "day_start": "09:00", "day_end": "21:00", "daily_cap": 120, "s_min": 30,
                 "s_target": 60, "s_max": 90, "brk": 15, "buffer": 120, "flex": 0, "task_cap": 0}
SEED = 5105
REPORT_SCHEMA = 1


@dataclass
class Metrics:
    status: str
    new_sessions: int
    planned_new: int
    kept: int
    demand: int
    unplaced: int
    coverage: float
    overlaps_busy: int
    overlaps_flex: int
    overlaps_sessions: int
    break_violations: int
    daily_cap_exceeded: int
    buffer_violations: int
    outside_window: int
    short_sessions: int
    planned_by_day: dict = field(default_factory=dict)
    task_cap_exceeded: int = 0

    @property
    def hard_violations(self) -> int:
        return (self.overlaps_busy + self.overlaps_flex + self.overlaps_sessions + self.break_violations
                + self.daily_cap_exceeded + self.buffer_violations + self.outside_window + self.short_sessions
                + self.task_cap_exceeded)


# ------------------------------------------------------------------ inputs

def _local(s: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def build_inputs(sc: dict):
    prefs = planner.Prefs(**{**DEFAULT_PREFS, **sc.get("prefs", {})})
    tz = ZoneInfo(prefs.tz)
    t0 = _local(sc["start"], tz)
    t1 = t0 + timedelta(days=sc.get("days", 3))
    tasks = [planner.TaskIn(t["id"], t.get("title", t["id"]), t["remaining"], _local(t["cutoff"], tz)) for t in sc["tasks"]]
    busy = [(_local(a, tz), _local(b, tz)) for a, b in sc.get("busy", [])]
    completed = {date.fromisoformat(d): m for d, m in sc.get("completed", {}).items()}
    kept = [{"task_id": k["task_id"], "task_title": k["task_id"], "phase": "study", "start": _local(k["start"], tz),
             "end": _local(k["end"], tz),
             "minutes": int((_local(k["end"], tz) - _local(k["start"], tz)).total_seconds() // 60)}
            for k in sc.get("kept", [])]
    return prefs, tz, t0, t1, tasks, busy, completed, kept


def run(sc: dict, kept_override: list[dict] | None = None) -> tuple[planner.Result, str]:
    prefs, tz, t0, t1, tasks, busy, completed, kept = build_inputs(sc)
    if kept_override is not None:
        kept = kept_override
    if not sc.get("calendar_ok", True):  # a failed calendar read: the service never plans on it
        return planner.Result(), plan_status(planner.Result(), ["calendar_snapshot_failed"], bool(tasks), False)
    r = planner.plan(tasks, busy, prefs, t0, t1, completed, kept)
    return r, plan_status(r, [], bool(tasks), True)


# ------------------------------------------------------------------ independent metrics

def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def measure(sc: dict, r: planner.Result, status: str) -> Metrics:
    prefs, tz, t0, t1, tasks, busy, completed, kept_in = build_inputs(sc)
    by_task = {t.id: t for t in tasks}
    sess = [(datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]), s) for s in r.sessions]
    flex = [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"])) for f in r.flex]
    new = [x for x in sess if not x[2].get("kept")]
    gap = timedelta(minutes=prefs.brk)
    ov_busy = sum(1 for s, e, _ in new for bs, be in busy if s < be and bs < e)
    ov_flex = sum(1 for s, e, _ in sess for fs, fe in flex if s < fe and fs < e)
    ov_sess = brk = 0
    ordered = sorted(sess, key=lambda x: x[0])
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            if b[0] < a[1]:
                ov_sess += 1
            elif b[0] < a[1] + gap:
                brk += 1
    per_day: dict[date, int] = {}
    new_per_day: dict[str, int] = {}
    for s, e, x in sess:
        d = s.astimezone(tz).date()
        per_day[d] = per_day.get(d, 0) + int((e - s).total_seconds() // 60)
        if not x.get("kept"):
            new_per_day[d.isoformat()] = new_per_day.get(d.isoformat(), 0) + int((e - s).total_seconds() // 60)
    cap_bad = sum(1 for d, m in per_day.items() if m + completed.get(d, 0) > prefs.daily_cap)
    # Per-task daily cap: one task's minutes on one day (written blocks included), on days this plan adds to.
    task_day: dict[tuple[str, date], int] = {}
    adds: set[tuple[str, date]] = set()
    for s, e, x in sess:
        k = (x["task_id"], s.astimezone(tz).date())
        task_day[k] = task_day.get(k, 0) + int((e - s).total_seconds() // 60)
        if not x.get("kept"):
            adds.add(k)
    task_bad = sum(1 for k, m in task_day.items() if prefs.task_cap and k in adds and m > prefs.task_cap)
    buf_bad = sum(1 for s, e, x in new if x["task_id"] in by_task
                  and e > by_task[x["task_id"]].cutoff - timedelta(minutes=prefs.buffer))
    outside = 0
    for s, e, _ in new:
        ls, le = s.astimezone(tz), e.astimezone(tz)
        if s < t0 or e > t1 or ls.date() != le.date() or ls.time() < _hm(prefs.day_start) or le.time() > _hm(prefs.day_end):
            outside += 1
    kept_by_task: dict[str, int] = {}
    for k in kept_in:
        kept_by_task[k["task_id"]] = kept_by_task.get(k["task_id"], 0) + k["minutes"]
    # Rule: what is left after written blocks and the other held-in-place blocks may be one session shorter than
    # the minimum.
    pinned: dict[str, int] = {}
    for a, b, x in new:
        if x.get("pinned"):
            pinned[x["task_id"]] = pinned.get(x["task_id"], 0) + int((b - a).total_seconds() // 60)

    def small_ok(a: datetime, b: datetime, x: dict) -> bool:
        if x["task_id"] not in by_task:
            return False
        held = kept_by_task.get(x["task_id"], 0) + pinned.get(x["task_id"], 0)
        if x.get("pinned"):
            held -= int((b - a).total_seconds() // 60)
        return 0 < by_task[x["task_id"]].remaining - held < prefs.s_min
    short = sum(1 for s, e, x in new if (e - s) < timedelta(minutes=prefs.s_min) and not small_ok(s, e, x)
                or (e - s) > timedelta(minutes=prefs.s_max))
    demand = sum(max(0, t.remaining - kept_by_task.get(t.id, 0)) for t in tasks)
    planned_new = sum(int((e - s).total_seconds() // 60) for s, e, x in new if x["task_id"] in by_task)
    covered_total = sum(t.remaining for t in tasks)
    covered = sum(min(t.remaining, kept_by_task.get(t.id, 0)) for t in tasks) + planned_new
    return Metrics(status=status, new_sessions=len(new), planned_new=planned_new, kept=sum(kept_by_task.values()),
                   demand=demand, unplaced=max(0, demand - planned_new),
                   coverage=round(covered / covered_total, 4) if covered_total else 1.0,
                   overlaps_busy=ov_busy, overlaps_flex=ov_flex, overlaps_sessions=ov_sess, break_violations=brk,
                   daily_cap_exceeded=cap_bad, buffer_violations=buf_bad, outside_window=outside, short_sessions=short,
                   planned_by_day=dict(sorted(new_per_day.items())), task_cap_exceeded=task_bad)


# ------------------------------------------------------------------ independent optimum (single task)

def optimum_single_task(sc: dict, r: planner.Result) -> int | None:
    """Most minutes one task can get under the rules, by exhaustive search over time slots. Deliberately shares no
    code with the planner: every day is walked slot by slot with a bitset of reachable totals. The weekly flex the
    planner reserved is a rule-mandated reservation, so it is treated as busy here too. None for multi-task inputs
    (their joint optimum is a different, much larger problem) and for failed calendar reads."""
    prefs, tz, t0, t1, tasks, busy, completed, kept = build_inputs(sc)
    if len(tasks) != 1 or not sc.get("calendar_ok", True):
        return None
    t = tasks[0]
    own_kept = sum(k["minutes"] for k in kept if k["task_id"] == t.id)
    demand = max(0, t.remaining - own_kept)
    if demand == 0:
        return 0
    brk = timedelta(minutes=prefs.brk)
    blocked = list(busy) + [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"])) for f in r.flex]
    blocked += [(k["start"] - brk, k["end"] + brk) for k in kept]
    quantities = [demand, prefs.s_min, prefs.s_max, prefs.brk, prefs.daily_cap, prefs.task_cap] + [
        x.hour * 60 + x.minute for iv in blocked for x in iv] + [t0.hour * 60 + t0.minute]
    step = 5 if all(q % 5 == 0 for q in quantities) else 1
    lengths = [demand] if demand < prefs.s_min else list(range(prefs.s_min, prefs.s_max + 1, step))
    limit = t.cutoff - timedelta(minutes=prefs.buffer)
    totals = 1  # bit k set = k*step minutes reachable over the days seen so far
    d = t0.astimezone(tz).date()
    while d <= t1.astimezone(tz).date():
        ws = max(datetime.combine(d, _hm(prefs.day_start), tz), t0)
        we = min(datetime.combine(d, _hm(prefs.day_end), tz), t1, limit)
        room = prefs.daily_cap - completed.get(d, 0) - sum(k["minutes"] for k in kept if k["start"].astimezone(tz).date() == d)
        if prefs.task_cap:  # this task's own written blocks that day count toward its per-task cap
            room = min(room, prefs.task_cap - sum(k["minutes"] for k in kept
                                                  if k["task_id"] == t.id and k["start"].astimezone(tz).date() == d))
        room = min(max(0, room), demand)
        day_mask = 1
        if we > ws and room > 0:
            n = int((we - ws).total_seconds() // 60) // step
            free = [not any(ws + timedelta(minutes=i * step) < be and bs < ws + timedelta(minutes=(i + 1) * step)
                            for bs, be in blocked) for i in range(n)]
            run = [0] * (n + 1)
            for i in range(n - 1, -1, -1):
                run[i] = run[i + 1] + 1 if free[i] else 0
            keep = (1 << (room // step + 1)) - 1
            reach = [0] * (n + 1)
            reach[0] = 1
            gap = prefs.brk // step if prefs.brk % step == 0 else -(-prefs.brk // step)
            for i in range(n):
                if not reach[i]:
                    continue
                reach[i + 1] |= reach[i]  # leave this slot empty
                for length in lengths:
                    k = length // step if length % step == 0 else None
                    if k and run[i] >= k:
                        j = min(n, i + k + gap)  # next session may start after the break
                        reach[j] |= (reach[i] << k) & keep
            day_mask = reach[n] | 1
        combined = 0
        for b in range(day_mask.bit_length()):
            if day_mask >> b & 1:
                combined |= totals << b
        totals = combined & ((1 << (demand // step + 1)) - 1)
        d += timedelta(days=1)
    return (totals.bit_length() - 1) * step


# ------------------------------------------------------------------ fixed scenarios

def _fmt(iso: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(iso).astimezone(tz).strftime("%Y-%m-%d %H:%M")


def check_fixed(sc: dict) -> dict:
    r, status = run(sc)
    m = measure(sc, r, status)
    tz = ZoneInfo({**DEFAULT_PREFS, **sc.get("prefs", {})}["tz"])
    exp = sc["expected"]
    checks = []

    def chk(name, expected, actual):
        checks.append({"check": name, "expected": expected, "actual": actual, "ok": expected == actual})

    if "status" in exp:
        chk("status", exp["status"], status)
    if "unplaced" in exp:
        chk("unplaced_minutes", exp["unplaced"], m.unplaced)
    if "planned_new" in exp:
        chk("planned_new_minutes", exp["planned_new"], m.planned_new)
    if "planned_by_day" in exp:
        chk("planned_by_day", exp["planned_by_day"], m.planned_by_day)
    if "sessions" in exp:
        chk("new_sessions", exp["sessions"],
            [[x["task_id"], _fmt(x["start"], tz), _fmt(x["end"], tz)] for x in r.sessions if not x.get("kept")])
    if "flex_minutes" in exp:
        chk("flex_minutes", exp["flex_minutes"],
            sum(int((datetime.fromisoformat(f["end"]) - datetime.fromisoformat(f["start"])).total_seconds() // 60) for f in r.flex))
    if exp.get("deterministic"):
        r2, _ = run(sc)
        chk("same_result_on_rerun", True, r2.sessions == r.sessions and r2.flex == r.flex)
    if "new_after_save" in exp:
        # "Save" the first plan: its new sessions become written blocks, then plan again.
        saved = [{**x, "start": datetime.fromisoformat(x["start"]), "end": datetime.fromisoformat(x["end"])}
                 for x in r.sessions]
        r3, st3 = run(sc, kept_override=saved)
        chk("new_minutes_after_save", exp["new_after_save"], measure(sc, r3, st3).planned_new)
    best = optimum_single_task(sc, r)
    if best is not None:
        chk("reaches_independent_optimum", best, m.planned_new)
    chk("hard_rule_violations", 0, m.hard_violations)
    return {"id": sc["id"], "title": sc["title"], "category": sc["category"], "known_gap": sc.get("known_gap"),
            "passed": all(c["ok"] for c in checks), "checks": checks, "metrics": asdict(m),
            "sessions": [[x["task_id"], _fmt(x["start"], tz), _fmt(x["end"], tz), bool(x.get("kept"))] for x in r.sessions]}


def load_fixed() -> list[dict]:
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


# ------------------------------------------------------------------ seeded scenarios

def generate(n: int = 200, seed: int = SEED) -> list[dict]:
    """Inputs only, from a fixed seed: the same n scenarios on every run and every machine."""
    rng = random.Random(seed)
    caps = random.Random(seed + 2)  # separate stream: adding the per-task cap left the other inputs unchanged
    base = datetime(2026, 11, 9, 9, 0)  # a Monday
    out = []
    for i in range(n):
        kind = ["dense_deadlines", "fragmented_free_time", "progress_today", "written_blocks", "short_remainders",
                "mixed"][i % 6]
        days = rng.randint(2, 6)
        cap = rng.choice([90, 120, 120, 180, 240])
        prefs = {"daily_cap": cap, "buffer": rng.choice([0, 60, 120]), "flex": rng.choice([0, 0, 60, 120]),
                 "task_cap": caps.choice([0, 0, 60, 90, 120])}
        start = base
        tasks = []
        for k in range(rng.randint(1, 4)):
            # Dense deadlines fall in the first two days; otherwise anywhere in the horizon.
            due_day = rng.randint(0, min(2, days)) if kind == "dense_deadlines" else rng.randint(1, days)
            due = start.replace(hour=rng.choice([12, 15, 18, 21])) + timedelta(days=due_day)
            rem = rng.choice([15, 20, 25]) if kind == "short_remainders" and k == 0 else rng.randrange(20, 241, 5)
            tasks.append({"id": f"T{k + 1}", "remaining": rem, "cutoff": due.isoformat()})
        busy = []
        per_day_blocks = (4, 8) if kind == "fragmented_free_time" else (0, 3)
        for d in range(days):
            day0 = start + timedelta(days=d)
            for _ in range(rng.randint(*per_day_blocks)):
                st = day0.replace(hour=rng.randint(9, 19), minute=rng.choice([0, 15, 30, 45]))
                busy.append([st.isoformat(), (st + timedelta(minutes=rng.choice([20, 30, 45, 60, 90, 120]))).isoformat()])
        completed = {}
        if kind in ("progress_today", "mixed"):
            completed[start.date().isoformat()] = rng.choice([30, 45, 60, min(cap, 90)])
        kept = []
        if kind in ("written_blocks", "mixed"):
            for _ in range(rng.randint(1, 2)):
                d = rng.randint(0, days - 1)
                st = (start + timedelta(days=d)).replace(hour=rng.randint(9, 18), minute=0)
                en = st + timedelta(minutes=rng.choice([30, 45, 60]))
                clash = any(_overlaps(st, en, b) for b in busy) or any(_overlaps(st, en, [k["start"], k["end"]]) for k in kept)
                day_load = completed.get(st.date().isoformat(), 0) + sum(
                    _minutes(k) for k in kept if k["start"][:10] == st.date().isoformat())
                if not clash and day_load + (en - st).seconds // 60 <= cap:
                    kept.append({"task_id": rng.choice([t["id"] for t in tasks] + ["OTHER"]),
                                 "start": st.isoformat(), "end": en.isoformat()})
        out.append({"id": f"R{i + 1:03d}", "title": kind, "category": kind, "start": start.isoformat(), "days": days,
                    "prefs": prefs, "tasks": tasks, "busy": busy, "completed": completed, "kept": kept,
                    # Every 7th mixed scenario simulates a failed calendar read.
                    "calendar_ok": not (kind == "mixed" and (i // 6) % 7 == 0)})
    return out


def _overlaps(s: datetime, e: datetime, iv: list[str]) -> bool:
    bs, be = datetime.fromisoformat(iv[0]), datetime.fromisoformat(iv[1])
    return s < be + timedelta(minutes=15) and bs - timedelta(minutes=15) < e


def _minutes(k: dict) -> int:
    return int((datetime.fromisoformat(k["end"]) - datetime.fromisoformat(k["start"])).total_seconds() // 60)


def score_seeded(n: int = 200, seed: int = SEED) -> dict:
    rows = []
    for sc in generate(n, seed):
        r, status = run(sc)
        m = measure(sc, r, status)
        rows.append({"id": sc["id"], "category": sc["category"], **asdict(m), "hard_violations": m.hard_violations,
                     "capacity_upper_bound": r.capacity_upper_bound, "single_task_optimum": optimum_single_task(sc, r)})
    planned = [x for x in rows if x["status"] != "needs_information"]
    single = [x for x in rows if x["single_task_optimum"] is not None]
    by_status: dict[str, int] = {}
    for x in rows:
        by_status[x["status"]] = by_status.get(x["status"], 0) + 1
    cov = sorted(x["coverage"] for x in planned)
    keys = ["overlaps_busy", "overlaps_flex", "overlaps_sessions", "break_violations", "daily_cap_exceeded",
            "buffer_violations", "outside_window", "short_sessions", "task_cap_exceeded"]
    return {
        "count": len(rows), "seed": seed, "by_status": dict(sorted(by_status.items())),
        "violations": {k: sum(x[k] for x in rows) for k in keys},
        "scenarios_with_any_violation": sum(1 for x in rows if x["hard_violations"]),
        "unplaced_minutes_total": sum(x["unplaced"] for x in planned),
        "scenarios_with_unplaced": sum(1 for x in planned if x["unplaced"] > 0),
        # Unplaced work that the capacity upper bound did not prove impossible. Some are truly impossible once breaks
        # and session lengths count (the bound ignores them), some are heuristic gaps: these need a human look.
        "heuristic_gaps": [x["id"] for x in planned if x["unplaced"] > 0 and x["status"] == "needs_adjustment"],
        "coverage": {"mean": round(sum(cov) / len(cov), 4) if cov else None, "min": cov[0] if cov else None,
                     "p10": cov[len(cov) // 10] if cov else None},
        # Single-task scenarios checked against the independent exhaustive optimum.
        "single_task_optimality": {
            "checked": len(single), "optimal": sum(1 for x in single if x["planned_new"] == x["single_task_optimum"]),
            "gap_minutes": sum(x["single_task_optimum"] - x["planned_new"] for x in single),
            "gaps": [x["id"] for x in single if x["planned_new"] != x["single_task_optimum"]]},
        "rows": rows,
    }


# ------------------------------------------------------------------ conflict repair

def score_repairs(n: int = 200, seed: int = SEED) -> dict:
    """For each seeded scenario with a plan, add one new meeting on top of a planned block (or, where the scenario
    has written blocks, on a written block whose calendar event is known) and run the repair options. The repaired
    plan is checked with the same independent metrics as above, against the busy time including the new meeting."""
    rng = random.Random(seed + 1)
    rows = []
    for sc in generate(n, seed):
        if not sc.get("calendar_ok", True):
            continue
        prefs, tz, t0, t1, tasks, busy, completed, kept = build_inputs(sc)
        base = planner.plan(tasks, busy, prefs, t0, t1, completed, kept)
        new = [x for x in base.sessions if not x.get("kept")]
        ids = {t.id for t in tasks}
        written = [{**k, "event_id": f"ev{i}"} for i, k in enumerate(kept)]
        targets = [("written", k) for k in written if k["task_id"] in ids] + [("suggested", x) for x in new]
        if not targets:
            continue
        kind, hit = targets[rng.randrange(len(targets))] if rng.random() < 0.5 else (
            ("suggested", new[rng.randrange(len(new))]) if new else targets[0])
        hs = datetime.fromisoformat(hit["start"]) if isinstance(hit["start"], str) else hit["start"]
        meet = (hs + timedelta(minutes=rng.choice([0, 15])), hs + timedelta(minutes=rng.choice([30, 60, 90, 120])))
        busy2 = sorted(busy + [meet])
        current = [{**x, "start": datetime.fromisoformat(x["start"]), "end": datetime.fromisoformat(x["end"])} for x in new]
        conflicts, opts = repair.build_options(tasks, busy2, prefs, t0, t1, completed, {}, written, current)
        if not opts:
            continue
        best = opts[0]
        sc2 = {**sc, "busy": sc["busy"] + [[meet[0].isoformat(), meet[1].isoformat()]],
               "kept": [k for k in sc["kept"] if not any(
                   r["start"] == _local(k["start"], tz).isoformat() for r in best.remove_written)]}
        if best.prefs is not None and best.prefs != prefs:  # a relaxed option is checked against the rule it relaxes
            sc2["prefs"] = {**sc.get("prefs", {}), "daily_cap": best.prefs.daily_cap, "flex": best.prefs.flex,
                            "task_cap": best.prefs.task_cap}
        m = measure(sc2, best.result, best.status)
        scratch = planner.plan(tasks, busy2, prefs, t0, t1, completed,
                               [k for k in kept if not repair.overlapping(k["start"], k["end"], [meet])])
        base_keys = {(x["task_id"], x["start"], x["end"]) for x in new}
        scratch_changed = len({(x["task_id"], x["start"], x["end"]) for x in scratch.sessions if not x.get("kept")} - base_keys)
        top_kept_rules = next((o for o in opts if not o.relaxed), None)
        rows.append({"id": sc["id"], "hit": kind, "conflicts": len(conflicts), "options": len(opts),
                     "written_conflict": any(c["written"] and c["task_id"] in ids for c in conflicts),
                     "strategy": best.strategy, "relaxed": best.relaxed, "hard_violations": m.hard_violations,
                     "unmet_before": base.unmet, "unmet_after": best.result.unmet,
                     "unmet_scratch": scratch.unmet, "changed": best.changed, "changed_scratch": scratch_changed,
                     "moved_written": len(best.remove_written), "min_slack": best.min_slack_minutes,
                     "relaxed_offered": sum(1 for o in opts if o.relaxed),
                     # an option relaxing a rule should only be offered when it places more than every rule-keeping one
                     "relaxed_needlessly": any(o.relaxed and top_kept_rules is not None
                                               and o.result.unmet >= top_kept_rules.result.unmet for o in opts)})
    k = len(rows)
    clean = [x for x in rows if x["unmet_after"] <= x["unmet_before"]]
    same = [x for x in rows if x["unmet_after"] == x["unmet_scratch"]]
    return {
        "count": k, "seed": seed,
        "hard_violations": sum(x["hard_violations"] for x in rows),
        "fully_resolved": sum(1 for x in rows if x["unmet_after"] == 0),
        "no_worse_than_before": len(clean),
        "no_worse_than_full_replan": sum(1 for x in rows if x["unmet_after"] <= x["unmet_scratch"]),
        # changed blocks compared where both place the same amount of work (otherwise more blocks can mean more placed)
        "same_unmet_as_full_replan": len(same),
        "avg_changed": round(sum(x["changed"] for x in same) / len(same), 2) if same else None,
        "avg_changed_full_replan": round(sum(x["changed_scratch"] for x in same) / len(same), 2) if same else None,
        "fewer_or_equal_changes": sum(1 for x in same if x["changed"] <= x["changed_scratch"]),
        "written_hits": sum(1 for x in rows if x["written_conflict"]),  # the meeting hit a written, movable block
        "written_moved": sum(1 for x in rows if x["moved_written"]),
        "by_strategy": {s_: sum(1 for x in rows if x["strategy"] == s_) for s_ in sorted({x["strategy"] for x in rows})},
        "relaxed_recommended": sum(1 for x in rows if x["relaxed"]),
        "relaxed_offered": sum(1 for x in rows if x["relaxed_offered"]),
        "relaxed_needlessly": sum(1 for x in rows if x["relaxed_needlessly"]),
        "rows": rows,
    }


# ------------------------------------------------------------------ estimate calibration (simulation)

CAL_GROUPS = {"accurate": (1.0, 1.0), "under": (1.2, 1.6), "over": (0.6, 0.85)}  # true actual/estimate bias


def score_calibration(n: int = 200, seed: int = SEED, tasks_per_student: int = 8, noise: float = 0.2) -> dict:
    """Simulated students, NOT real data. Each has a fixed bias (accurate / underestimates / overestimates, one
    third each) and per-task noise; tasks are done one after another. Before each task the calibration rules see
    only that student's earlier finished tasks. Compares the error of the raw estimate with the estimate the
    student would have if they accepted every suggestion."""
    rng = random.Random(seed + 3)
    rows = []
    for i in range(n):
        group = list(CAL_GROUPS)[i % 3]
        lo, hi = CAL_GROUPS[group]
        bias = rng.uniform(lo, hi)
        history: list[calibration.Sample] = []
        for k in range(tasks_per_student):
            est = rng.randrange(60, 361, 15)
            actual = max(15, round(est * bias * math.exp(rng.gauss(0, noise))))
            b = calibration.bias_for(history, "SIM", "submission")
            new = calibration.suggest_minutes(est, 0, b) if b else None
            used = new or est
            rows.append({"student": i, "group": group, "k": k, "estimate": est, "actual": actual, "suggested": new,
                         "raw_error": abs(est - actual) / actual, "cal_error": abs(used - actual) / actual,
                         "raw_under": est < 0.8 * actual, "cal_under": used < 0.8 * actual})
            history.append(calibration.Sample(f"s{i}t{k}", "", None, "SIM", "submission", est, actual, True))

    def med(xs):
        return round(calibration.median(xs), 3) if xs else None

    late = [r for r in rows if r["k"] >= calibration.MIN_SAMPLES]  # tasks where a suggestion was possible
    by_group = {}
    for g in CAL_GROUPS:
        rs = [r for r in late if r["group"] == g]
        by_group[g] = {"tasks": len(rs), "suggested": sum(1 for r in rs if r["suggested"]),
                       "raw_median_error": med([r["raw_error"] for r in rs]),
                       "calibrated_median_error": med([r["cal_error"] for r in rs]),
                       "raw_underestimated": sum(r["raw_under"] for r in rs),
                       "calibrated_underestimated": sum(r["cal_under"] for r in rs)}
    return {"students": n, "seed": seed, "tasks_per_student": tasks_per_student, "noise_sd": noise,
            "groups": {g: list(v) for g, v in CAL_GROUPS.items()}, "by_group": by_group,
            "raw_median_error": med([r["raw_error"] for r in late]),
            "calibrated_median_error": med([r["cal_error"] for r in late]),
            "first_tasks_without_suggestion": sum(1 for r in rows if r["k"] < calibration.MIN_SAMPLES and r["suggested"]) == 0}


# ------------------------------------------------------------------ report

def build_report(n: int = 200, seed: int = SEED) -> dict:
    fixed = [check_fixed(sc) for sc in load_fixed()]
    return {"schema_version": REPORT_SCHEMA, "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "fixed": {"total": len(fixed), "passed": sum(x["passed"] for x in fixed),
                      "failed": [x["id"] for x in fixed if not x["passed"]],
                      "known_gaps": [x["id"] for x in fixed if x["known_gap"]], "results": fixed},
            "seeded": score_seeded(n, seed), "repairs": score_repairs(n, seed), "calibration": score_calibration(n, seed)}


def markdown(rep: dict) -> str:
    f, s = rep["fixed"], rep["seeded"]
    lines = ["# 排程评测报告 / Planner evaluation", "", f"- 生成时间：{rep['generated_at']}（结构版本 {rep['schema_version']}）",
             f"- 固定场景：{f['passed']}/{f['total']} 通过" + (f"；未通过：{', '.join(f['failed'])}" if f["failed"] else ""),
             f"- 已知缺口（预期按规则写，当前算法未达到）：{', '.join(f['known_gaps']) or '无'}",
             f"- 随机场景：{s['count']} 组，种子 {s['seed']}", "",
             "## 固定场景", "", "| 编号 | 场景 | 类别 | 结果 | 状态 | 新增分钟 | 未排分钟 | 覆盖率 | 违规 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for x in f["results"]:
        m = x["metrics"]
        mark = "通过" if x["passed"] else ("已知缺口" if x["known_gap"] else "**未通过**")
        lines.append(f"| {x['id']} | {x['title']} | {x['category']} | {mark} | {m['status']} | {m['planned_new']} | "
                     f"{m['unplaced']} | {m['coverage']:.0%} | {sum(m[k] for k in ('overlaps_busy', 'overlaps_flex', 'overlaps_sessions', 'break_violations', 'daily_cap_exceeded', 'buffer_violations', 'outside_window', 'short_sessions', 'task_cap_exceeded'))} |")
    for x in f["results"]:
        bad = [c for c in x["checks"] if not c["ok"]]
        if bad:
            lines += ["", f"**{x['id']} 不一致项**：" + "；".join(f"{c['check']} 预期 {c['expected']}，实际 {c['actual']}" for c in bad)]
            if x["known_gap"]:
                lines.append(f"说明：{x['known_gap']}")
    lines += ["", "## 随机场景汇总", "", f"- 状态分布：{s['by_status']}",
              f"- 硬性规则违规：{s['violations']}（出现违规的场景 {s['scenarios_with_any_violation']} 组）",
              f"- 未安排分钟合计：{s['unplaced_minutes_total']}（{s['scenarios_with_unplaced']} 组有未安排）",
              f"- 覆盖率：平均 {s['coverage']['mean']}，最低 {s['coverage']['min']}，P10 {s['coverage']['p10']}",
              f"- 单任务场景与独立穷举最优解对比：{s['single_task_optimality']['optimal']}/{s['single_task_optimality']['checked']} 达到最优，"
              f"差距合计 {s['single_task_optimality']['gap_minutes']} 分钟"
              + (f"（{', '.join(s['single_task_optimality']['gaps'][:10])}）" if s['single_task_optimality']['gaps'] else ""),
              f"- 未证明不可行却有未安排（可能是真的放不下，也可能是算法缺口，需人工看）：{len(s['heuristic_gaps'])} 组"
              + (f"，例如 {', '.join(s['heuristic_gaps'][:10])}" if s["heuristic_gaps"] else ""),
              "", "注：零违规不等于排得好（完全不安排也零违规），请同时看覆盖率和未安排分钟。固定场景的预期结果需人工复核。",
              "单任务最优解由评测代码独立穷举（逐个时间格），不调用排程器；多任务场景的整体最优是更大的组合问题，未做穷举。"]
    rp = rep.get("repairs")
    if rp:
        lines += ["", "## 冲突修复（在随机场景上加一个新会议）", "",
                  f"- 场景：{rp['count']} 组（其中新会议碰到已写入学习块的 {rp['written_hits']} 组，推荐方案都给出了移动：{rp['written_moved']} 组）",
                  f"- 推荐方案的硬性规则违规（独立检查，含新会议）：{rp['hard_violations']}",
                  f"- 完全解决（无未安排）：{rp['fully_resolved']}/{rp['count']}；未安排不比加会议前更多：{rp['no_worse_than_before']}/{rp['count']}",
                  f"- 未安排不比“整周从头重排”更多：{rp['no_worse_than_full_replan']}/{rp['count']}",
                  f"- 排进同样多工作的 {rp['same_unmet_as_full_replan']} 组中，平均改动的学习块：推荐方案 {rp['avg_changed']}，"
                  f"整周从头重排 {rp['avg_changed_full_replan']}；推荐方案改动不多于从头重排的有 {rp['fewer_or_equal_changes']} 组",
                  f"- 推荐方案的策略分布：{rp['by_strategy']}",
                  f"- 推荐方案放宽了你的规则：{rp['relaxed_recommended']} 组；"
                  f"额外提供“放宽规则能多排多少”的方案：{rp['relaxed_offered']} 组；放宽却并没多排的：{rp['relaxed_needlessly']} 组",
                  "", "注：会议可能真的占掉了截止前唯一的空闲时间，所以“完全解决”不是 100% 也可能是对的；"
                  "关键是不比加会议前、也不比从头重排更差，同时改动更少。"]
    cal = rep.get("calibration")
    if cal:
        names = {"accurate": "估计准确的学生", "under": "习惯低估的学生", "over": "习惯高估的学生"}
        lines += ["", "## 估计校准（模拟，不是真实学生数据）", "",
                  f"- {cal['students']} 个模拟学生，每人依次完成 {cal['tasks_per_student']} 个任务；三类各占三分之一，"
                  f"真实用时/估计的偏差范围 {cal['groups']}，每个任务另有随机波动（对数标准差 {cal['noise_sd']}）",
                  "- 每个任务开始前，校准规则只看到该学生之前完成的任务；“校准后”假设学生接受了每条建议",
                  "- 前 3 个任务没有任何建议：" + ("是" if cal["first_tasks_without_suggestion"] else "否"),
                  f"- 全部可给建议的任务：估计误差中位数 {cal['raw_median_error']:.1%} → {cal['calibrated_median_error']:.1%}", "",
                  "| 学生类型 | 任务数 | 给出建议 | 误差中位数（原始 → 校准后） | 估计少于实际 80% 的任务（原始 → 校准后） |",
                  "|---|---|---|---|---|"]
        for g, v in cal["by_group"].items():
            lines.append(f"| {names[g]} | {v['tasks']} | {v['suggested']} | {v['raw_median_error']:.1%} → {v['calibrated_median_error']:.1%} | "
                         f"{v['raw_underestimated']} → {v['calibrated_underestimated']} |")
        lines += ["", "注：缩短估计需要至少 5 个已完成任务，并且只缩一半差距，所以高估型学生的误差改善较少，"
                  "但由此新增的明显低估很少（见最后一列；低估会导致赶不上截止）。参数是假设，用来检查规则的方向和安全性，不能当作真实准确率。"]
    return "\n".join(lines) + "\n"
