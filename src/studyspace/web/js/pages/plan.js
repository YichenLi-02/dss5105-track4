// Study plan (gate 2): a draft replaces nothing until the student adopts it.
import { api } from "../api.js";
import { cantMakeIt, quickConfirm, recordDone } from "../actions.js";
import { openFocus } from "../focus.js";
import { icon } from "../icons.js";
import {
  WARNING_TEXT, addDays, busy, courseIndex, courseTag, dueLabel, esc, fmtDate, fmtDateTime, fmtMinutes, fmtRange, fmtTime, hours, menu,
  minutesBetween, modal, mondayOf, sgDate, sgParts, showError, toast,
} from "../util.js";

const DAY_START = 8, DAY_END = 22, PX_PER_HOUR = 40;
let draft = null;     // POST /api/plans/draft response, kept until adopted or discarded
let dismissedFor = null;  // input version of a draft the student discarded: don't propose the same one again
let weekStart = null;
let view = null;

export async function render(root, ctx, params) {
  const [current, tasks, slots, settings, cands, version] = await Promise.all([
    api.get("/api/plans/current"), api.get("/api/tasks"), api.get("/api/calendar"), api.get("/api/settings"),
    api.get("/api/candidates?status=pending"), api.get("/api/plans/version"),
  ]);
  const inputs = version.input_version;
  const now = ctx.workspace.now;
  if (!weekStart) weekStart = mondayOf(sgDate(now));
  if (!view) view = window.matchMedia("(max-width: 820px)").matches ? "list" : "week";
  const taskById = Object.fromEntries(tasks.map((t) => [t.task_id, t]));
  const openTasks = tasks.filter((t) => t.status === "open");
  const plannable = openTasks.filter((t) => t.kind === "deliverable" && t.remaining_minutes > 0 && t.due_at > now);

  // the plan follows the student's changes: a stale draft is redrafted, and a saved plan that no longer fits
  // gets a proposed update straight away (still only saved when adopted)
  const wantsUpdate = params?.get("replan") === "1";
  if (wantsUpdate) history.replaceState(null, "", "#/plan");
  let refreshed = false;
  if (draft && draft.based_on !== inputs) { draft = null; refreshed = true; }
  const behind = current && current.replan_reasons.length;
  const firstPlan = !current && plannable.length;
  if (!draft && (wantsUpdate || ((firstPlan || behind || refreshed) && dismissedFor !== inputs))) {
    try { draft = await api.post("/api/plans/draft", {}); } catch (err) { showError(err); }  // the banner says what changed
  }

  const showing = draft ? "draft" : current ? "saved" : "none";
  const result = draft ? draft.result : current?.result;
  const blocks = draft ? draftBlocks(draft, current) : current?.blocks || [];
  const weekEnd = addDays(weekStart, 6);
  const inWeek = (iso) => { const d = sgDate(iso); return d >= weekStart && d <= weekEnd; };
  const weekBlocks = blocks.filter((b) => inWeek(b.start));
  const lede = showing === "draft" ? "A proposal inside your free hours. Nothing changes until you adopt it."
    : showing === "saved" ? "Your saved plan. Start, finish or move sessions as the week goes."
    : "Confirm tasks and Studyspace fits them into your free hours.";

  root.innerHTML = `
    <div class="page-head">
      <div><h1>Study plan</h1><p class="lede">${lede}</p></div>
      <div class="row">
        <button class="btn small" id="edit-hours">${icon("clock", 15)} Your hours</button>
        ${current && !draft ? `<button class="btn small" id="export">${icon("calendar", 15)} Export to calendar</button>` : ""}
        ${showing !== "draft" && (current || plannable.length) ? `<button class="btn small ${current?.replan_reasons.length ? "primary" : ""}" id="generate">${icon("sync", 15)} ${current ? "Update plan" : "Make plan"}</button>` : ""}
      </div>
    </div>
    ${notices(showing, current, draft, plannable, now)}
    <div class="plan-toolbar">
      <div class="week-nav">
        <button class="icon-btn" data-week="-1" aria-label="Previous week">${icon("chevron", 16).replace("<path", '<path transform="rotate(90 12 12)"')}</button>
        <h2>${esc(fmtDate(weekStart + "T12:00:00+08:00"))} – ${esc(fmtDate(weekEnd + "T12:00:00+08:00"))}</h2>
        <button class="icon-btn" data-week="1" aria-label="Next week">${icon("chevron", 16).replace("<path", '<path transform="rotate(-90 12 12)"')}</button>
        ${weekStart !== mondayOf(sgDate(now)) ? `<button class="btn tiny ghost" data-week="0">This week</button>` : ""}
      </div>
      <div class="row">
        ${pendingThisWeek(cands, weekStart) ? `<span class="chip outline dashed" title="Dashed deadlines on the calendar are found but not confirmed; click one to confirm it">${pendingThisWeek(cands, weekStart)} to confirm</span>` : ""}
        ${statusPill(showing, current)}
        <div class="tabs"><button data-view="week" class="${view === "week" ? "active" : ""}">Week</button><button data-view="list" class="${view === "list" ? "active" : ""}">List</button></div>
      </div>
    </div>
    <div class="grid">
      <div class="stack">
        <section class="card plan-card">
          ${showing === "none" && !plannable.length ? `<div class="plan-hint">${icon("clock", 18)}<span>${cands.length ? `<b>Click a dashed deadline to confirm it.</b> Studyspace then fits the work into your free hours.` : `<b>Nothing to plan yet.</b> Confirmed tasks appear here as study sessions.`}</span><a class="btn small" href="#/tasks">All tasks</a></div>` : ""}
          ${view === "week" ? weekGrid(weekBlocks, slots, tasks, taskById, now, showing, settings, cands) : listView(weekBlocks, slots, tasks, taskById, now, showing, cands)}
          <div class="legend plan-legend"><span><i class="lg-study"></i>Study</span><span><i class="lg-busy"></i>Class or meeting</span><span><i class="lg-event"></i>Exam or event</span><span><i class="lg-free"></i>Free hours</span><span><i class="lg-due"></i>Deadline</span><span><i class="lg-check"></i>Deadline to confirm</span></div>
        </section>
      </div>
      <aside class="stack">${sidePanel(result, blocks, weekBlocks, openTasks, taskById, settings, showing)}</aside>
    </div>`;

  bind(root, ctx, { current, taskById, settings, slots, now, blocks });
  if (params?.get("edit") === "hours") {
    history.replaceState(null, "", "#/plan");
    hoursDialog(ctx, settings, slots);
  }
}

function draftBlocks(d, current) {
  const added = new Set((d.changes?.added || []).map((b) => `${b.task_id}|${b.start}`));
  const lockedKeys = new Set((d.result.retained_locked_blocks || []).map((b) => `${b.task_id}|${b.start}`));
  const doneBlocks = (current?.blocks || []).filter((b) => b.done);  // finished work stays visible in a draft
  const all = [...d.result.blocks, ...d.result.retained_locked_blocks, ...doneBlocks];
  const doneKeys = new Set(doneBlocks.map((b) => `${b.task_id}|${b.start}`));
  return all.map((b) => ({ ...b, locked: lockedKeys.has(`${b.task_id}|${b.start}`), done: doneKeys.has(`${b.task_id}|${b.start}`), added: d.changes?.had_saved_plan && added.has(`${b.task_id}|${b.start}`) }))
    .sort((a, b) => a.start.localeCompare(b.start));
}

function statusPill(showing, current) {
  if (showing === "draft") return `<span class="chip">Draft · not saved</span>`;
  if (showing === "saved") return current.replan_reasons.length ? `<span class="chip amber">May be out of date</span>` : `<span class="chip green">${icon("check", 12)} Saved</span>`;
  return `<span class="chip outline">No plan yet</span>`;
}

function notices(showing, current, d, plannable, now) {
  if (showing === "draft") {
    const c = d.changes;
    const r = d.result;
    const missing = r.unscheduled.reduce((n, u) => n + u.minutes, 0);
    const planned = r.blocks.reduce((n, b) => n + minutesBetween(b.start, b.end), 0);
    const summary = c.had_saved_plan
      ? `${c.added.length} new or moved, ${c.removed.length} removed, ${c.kept} unchanged compared with your saved plan.`
      : `${r.blocks.length} sessions, ${fmtMinutes(planned)} in total${missing ? `; ${fmtMinutes(missing)} does not fit` : ", everything fits"}.`;
    return `<div class="banner draft-banner"><span class="attn-icon purple">${icon("spark", 16)}</span>
      <div><b>${c.had_saved_plan ? "Here's an updated plan" : "Here's a plan for your tasks"}</b><span>${esc(summary)} Checked against your rules: no clashes, daily limit, breaks, deadlines.</span></div>
      <div class="row"><button class="btn small ghost" id="discard">Discard</button><button class="btn small primary" id="adopt">${icon("check", 15)} Adopt and save</button></div></div>`;
  }
  if (showing === "saved" && current.replan_reasons.length) {
    return `<div class="banner warn-banner"><span class="attn-icon amber">${icon("sync", 16)}</span>
      <div><b>Your plan may no longer fit</b><span>${esc(current.replan_reasons.join("; "))}</span></div>
      <button class="btn small primary" id="generate-banner">Update plan</button></div>`;
  }
  return "";
}

function fixedItems(slots, tasks, start, end) {
  const busyItems = slots.filter((s) => s.kind === "busy" && s.end > start && s.start < end).map((s) => ({ ...s, type: "busy", title: s.label || "Busy" }));
  const events = tasks.filter((t) => t.kind === "event" && t.status === "open").map((t) => ({
    start: t.due_at, end: new Date(new Date(t.due_at).getTime() + (t.remaining_minutes || 60) * 60000).toISOString(), type: "event", title: t.title, course_code: t.course_code,
  })).filter((e) => e.end > start && e.start < end);
  return [...busyItems, ...events];
}

function candDue(c) {
  return c.due_at || (c.due_date ? `${c.due_date}T23:59:00+08:00` : null);
}

function pendingThisWeek(cands, start) {
  const end = addDays(start, 6);
  return cands.filter((c) => { const d = candDue(c); return d && sgDate(d) >= start && sgDate(d) <= end; }).length;
}

/** Everything due on a day: confirmed deadlines (solid) and found-but-unconfirmed ones (dashed, clickable). */
function deadlinesOn(day, tasks, cands) {
  const confirmed = tasks.filter((t) => t.kind === "deliverable" && t.status === "open" && sgDate(t.due_at) === day)
    .map((t) => ({ kind: "task", id: t.task_id, title: t.title, course: t.course_code, at: t.due_at, timed: true }));
  const found = cands.filter((c) => { const d = candDue(c); return d && sgDate(d) === day; })
    .map((c) => ({ kind: "cand", id: c.candidate_id, title: c.title, course: c.course_code, at: candDue(c), timed: Boolean(c.due_at) && !c.flags.includes("MIDNIGHT_AMBIGUITY") }));
  return [...confirmed, ...found].sort((a, b) => a.at.localeCompare(b.at));
}

function dueChip(d) {
  const label = d.timed ? fmtTime(d.at) : "time?";
  if (d.kind === "cand") {
    return `<button class="due-chip k${courseIndex(d.course)} pending" data-cand="${esc(d.id)}" title="Found in your messages, not confirmed yet: ${esc(d.title)}. Click to confirm.">${icon("clock", 11)}<span>${esc(d.title)}</span><b>${esc(label)}</b></button>`;
  }
  return `<span class="due-chip k${courseIndex(d.course)}" title="Due ${esc(fmtDateTime(d.at))}: ${esc(d.title)}">${icon("flag", 11)}<span>${esc(d.title)}</span><b>${esc(label)}</b></span>`;
}

function weekGrid(blocks, slots, tasks, taskById, now, showing, settings, cands = []) {
  const days = [...Array(7)].map((_, i) => addDays(weekStart, i));
  const startIso = `${weekStart}T00:00:00+08:00`, endIso = `${addDays(weekStart, 7)}T00:00:00+08:00`;
  const fixed = fixedItems(slots, tasks, startIso, endIso);
  const free = slots.filter((s) => s.kind === "available" && s.end > startIso && s.start < endIso);
  const dues = tasks.filter((t) => t.kind === "deliverable" && t.status === "open" && t.due_at >= startIso && t.due_at < endIso);
  const top = (iso) => { const p = sgParts(iso); return Math.max(0, (p.h + p.min / 60 - DAY_START) * PX_PER_HOUR); };
  const height = (a, b) => Math.max(16, Math.min(minutesBetween(a, b) / 60, DAY_END - DAY_START) * PX_PER_HOUR);
  const today = sgDate(now);
  const colH = (DAY_END - DAY_START) * PX_PER_HOUR;
  const limit = settings.plan.max_study_minutes_per_day;
  const cols = days.map((d) => {
    const on = (iso) => sgDate(iso) === d;
    const inner = [
      ...free.filter((s) => on(s.start)).map((s) => `<div class="slot-bg" style="top:${top(s.start)}px;height:${height(s.start, s.end)}px"></div>`),
      ...fixed.filter((f) => on(f.start)).map((f) => `<div class="wg-block ${f.type}" style="top:${top(f.start)}px;height:${height(f.start, f.end)}px" title="${esc(f.title)} ${esc(fmtRange(f.start, f.end))}">${esc(f.title)}</div>`),
      ...blocks.filter((b) => on(b.start)).map((b) => {
        const t = taskById[b.task_id];
        const h = height(b.start, b.end);
        return `<button class="wg-block study k${courseIndex(t?.course_code)} ${b.done || b.task_done ? "done" : ""} ${b.conflict ? "conflict" : ""} ${b.added ? "added" : ""}" style="top:${top(b.start)}px;height:${h}px"
          data-block='${esc(JSON.stringify({ task_id: b.task_id, start: b.start, end: b.end, locked: b.locked, done: b.done || b.task_done }))}' title="${esc(t?.title || b.task_id)} · ${esc(fmtRange(b.start, b.end))}">
          <span class="wb-title">${b.locked ? icon("lock", 10) + " " : ""}${b.done ? "✓ " : ""}${esc(t?.title || b.task_id)}</span>${h >= 34 ? `<span class="wb-time">${esc(fmtRange(b.start, b.end))}</span>` : ""}</button>`;
      }),
      ...dues.filter((t) => on(t.due_at)).map((t) => `<div class="wg-due" style="top:${Math.min(colH - 2, top(t.due_at))}px" title="Due: ${esc(t.title)} ${esc(fmtDateTime(t.due_at))}"><span>${esc(t.title)}</span></div>`),
      ...cands.filter((c) => c.due_at && !c.flags.includes("MIDNIGHT_AMBIGUITY") && on(c.due_at)).map((c) => `<div class="wg-due pending" style="top:${Math.min(colH - 2, top(c.due_at))}px" title="To confirm: ${esc(c.title)}"></div>`),
      d === today ? `<div class="wg-now" style="top:${top(now)}px"></div>` : "",
    ].join("");
    return `<div class="wg-col ${d < today ? "past" : ""}" style="height:${colH}px">${inner}</div>`;
  });
  const hourLabels = [...Array(DAY_END - DAY_START)].map((_, i) => `<div class="wg-hour">${String(DAY_START + i).padStart(2, "0")}:00</div>`).join("");
  return `<div class="table-wrap"><div class="week-grid">
    <div class="wg-head"></div>
    ${days.map((d) => {
      const p = sgParts(d + "T12:00:00+08:00");
      const load = blocks.filter((b) => sgDate(b.start) === d).reduce((n, b) => n + minutesBetween(b.start, b.end), 0);
      return `<div class="wg-head ${d === today ? "today" : ""}">${p.weekday}<b>${p.d}</b>
        <span class="day-meter" title="${esc(fmtMinutes(load) || "0 min")} of ${esc(fmtMinutes(limit))}"><span style="width:${Math.min(100, (load / limit) * 100)}%"></span></span></div>`;
    }).join("")}
    <div class="wg-lane-label">Due</div>
    ${days.map((d) => `<div class="wg-lane ${d === today ? "today" : ""}">${deadlinesOn(d, tasks, cands).map(dueChip).join("")}</div>`).join("")}
    <div class="wg-hours">${hourLabels}</div>
    ${cols.join("")}
  </div></div>`;
}

function listView(blocks, slots, tasks, taskById, now, showing, cands = []) {
  const days = [...Array(7)].map((_, i) => addDays(weekStart, i));
  const startIso = `${weekStart}T00:00:00+08:00`, endIso = `${addDays(weekStart, 7)}T00:00:00+08:00`;
  const fixed = fixedItems(slots, tasks, startIso, endIso);
  const today = sgDate(now);
  const groups = days.map((d) => {
    const items = [
      ...blocks.filter((b) => sgDate(b.start) === d).map((b) => ({ kind: "study", ...b })),
      ...fixed.filter((f) => sgDate(f.start) === d).map((f) => ({ kind: f.type, ...f })),
    ].sort((a, b) => a.start.localeCompare(b.start));
    const dueToday = deadlinesOn(d, tasks, cands);
    if (!items.length && !dueToday.length) return "";
    const p = sgParts(d + "T12:00:00+08:00");
    const load = items.filter((i) => i.kind === "study").reduce((n, b) => n + minutesBetween(b.start, b.end), 0);
    return `<div class="day-group ${d < today ? "past" : ""}"><div class="day-label ${d === today ? "today" : ""}">${p.weekday}<small>${esc(fmtDate(d + "T12:00:00+08:00"))}${d === today ? " · today" : ""}</small>${load ? `<small>${esc(fmtMinutes(load))} study</small>` : ""}</div>
      <div class="sessions">${dueToday.length ? `<div class="due-row">${dueToday.map(dueChip).join("")}</div>` : ""}${items.map((it) => it.kind === "study" ? sessionRow(it, taskById, showing, now) : `
        <div class="session ${it.kind === "event" ? "event" : "fixed"}"><span class="s-time">${esc(fmtRange(it.start, it.end))}</span><span><span class="s-title">${esc(it.title)}</span><div class="s-sub">${it.kind === "event" ? "exam or event" : "fixed"}</div></span><span></span></div>`).join("")}</div></div>`;
  }).join("");
  return groups || `<div class="empty">No sessions or classes this week.</div>`;
}

function sessionRow(b, taskById, showing, now) {
  const t = taskById[b.task_id];
  const past = b.end <= now;
  const data = esc(JSON.stringify({ task_id: b.task_id, start: b.start, end: b.end, locked: b.locked, done: b.done }));
  if (b.task_done && !b.done) {
    return `<div class="session k${courseIndex(t?.course_code)} done"><span class="s-time">${esc(fmtRange(b.start, b.end))}</span>
      <span><span class="s-title">${esc(t?.title || b.task_id)}</span><div class="s-sub">finished early · update the plan to free this time</div></span><span class="chip green">Spare</span></div>`;
  }
  const actions = showing === "saved" && !b.done ? `
    ${!past ? `<button class="btn tiny" data-focus-block='${data}' title="Start a focus timer">${icon("play", 13)}</button>` : ""}
    <button class="btn tiny" data-done-block='${data}'>${icon("check", 13)} Done</button>
    <button class="icon-btn small" data-more='${data}' aria-label="More actions">⋯</button>`
    : b.done ? `<span class="chip green">Done</span>` : b.locked ? `<span class="chip">${icon("lock", 11)} Locked</span>` : b.added ? `<span class="chip green">New</span>` : "";
  return `<div class="session k${courseIndex(t?.course_code)} ${b.done ? "done" : ""} ${b.conflict ? "conflict" : ""} ${b.added ? "added" : ""}">
    <span class="s-time">${esc(fmtRange(b.start, b.end))}</span>
    <span><span class="s-title">${b.locked ? icon("lock", 11) + " " : ""}${esc(t?.title || b.task_id)}</span><div class="s-sub">${courseTag(t?.course_code)}${t ? `due ${esc(dueLabel(t.due_at, now))}` : ""}${b.conflict ? " · clashes with a fixed commitment" : ""}${past && !b.done && showing === "saved" ? " · did it happen?" : ""}</div></span>
    <span class="s-actions">${actions}</span>
  </div>`;
}

function sidePanel(result, blocks, weekBlocks, openTasks, taskById, settings, showing) {
  const p = settings.plan;
  const weekMinutes = weekBlocks.filter((b) => !b.done).reduce((n, b) => n + minutesBetween(b.start, b.end), 0);
  const missing = (result?.unscheduled || []).reduce((n, u) => n + u.minutes, 0);
  const warnings = result?.warnings || [];
  const results = result?.task_results || [];
  return `
  <section class="card glance"><div class="card-body">
    <p class="side-title">This week</p>
    <div class="big-number">${hours(weekMinutes)}<small>h</small></div>
    <p class="small" style="color:var(--green);margin:6px 0 14px">${showing === "none" ? "no plan yet" : "of focused work planned"}</p>
    <div class="kv"><span>Does not fit</span><b style="${missing ? "color:var(--red)" : ""}">${missing ? fmtMinutes(missing) : "nothing"}</b></div>
    <div class="kv"><span>Confirmed tasks</span><b>${openTasks.filter((t) => t.kind === "deliverable").length}</b></div>
    <div class="kv"><span>Locked sessions</span><b>${blocks.filter((b) => b.locked).length}</b></div>
  </div></section>
  ${warnings.length ? `<section class="card"><div class="card-head"><h2>Things to know</h2></div><div class="card-body stack" style="gap:8px">
    ${warnings.map((w) => `<div class="alert ${["INSUFFICIENT_TIME", "PAST_DEADLINE", "LOCK_CONFLICT"].includes(w.code) ? "red" : "amber"}"><strong>${esc(WARNING_TEXT[w.code] || w.code)}</strong><span>${esc(w.message)}</span></div>`).join("")}
    ${missing ? `<p class="small muted" style="margin:4px 0 0">Add free hours, lower an estimate, or talk to the course team. Studyspace never squeezes work into the night or past a deadline.</p>` : ""}
  </div></section>` : ""}
  ${results.length ? `<section class="card"><div class="card-head"><h2>Task coverage</h2></div><div class="card-body" style="padding-top:6px">
    ${results.map((r) => {
      const t = taskById[r.task_id];
      const planned = r.scheduled_minutes + r.locked_future_minutes;
      const pct = r.reserved_minutes ? Math.round((planned / r.reserved_minutes) * 100) : 100;
      return `<div class="task-line"><div class="row between"><span class="row" style="gap:6px;min-width:0">${courseTag(t?.course_code)}<b class="ellipsis">${esc(t?.title || r.task_id)}</b></span><span class="tiny muted">${fmtMinutes(planned) || "0"} / ${fmtMinutes(r.reserved_minutes)}</span></div>
        <span class="meter wide ${pct < 100 ? "short" : ""}"><span style="width:${Math.min(100, pct)}%"></span></span></div>`;
    }).join("")}
  </div></section>` : ""}
  <section class="card"><div class="card-head"><h2>Your pace</h2><button class="btn tiny ghost" id="edit-pace">Edit</button></div><div class="card-body" style="padding-top:4px">
    <div class="kv" style="border-top:0"><span>Daily focus limit</span><b>${fmtMinutes(p.max_study_minutes_per_day)}</b></div>
    <div class="kv"><span>Longest session</span><b>${p.max_block_minutes} min, then a ${p.min_break_minutes}-min break</b></div>
    <div class="kv"><span>Finish before deadlines</span><b>${hours(p.target_buffer_minutes)} h early</b></div>
    <div class="kv"><span>Study window</span><b>${esc(p.study_day_start)}–${esc(p.study_day_end)}</b></div>
  </div></section>`;
}

function bind(root, ctx, { current, taskById, settings, slots, now, blocks }) {
  root.querySelectorAll("[data-week]").forEach((b) => b.addEventListener("click", () => {
    const step = +b.dataset.week;
    weekStart = step === 0 ? mondayOf(sgDate(now)) : addDays(weekStart, step * 7);
    ctx.refresh();
  }));
  root.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => { view = b.dataset.view; ctx.refresh(); }));

  const generate = (btn) => busy(btn, async () => {
    try {
      draft = await api.post("/api/plans/draft", {});
      const r = draft.result;
      toast(r.status === "complete" ? "Draft ready. Every task fits." : r.status === "partial" ? "Draft ready, but some work does not fit." : "Draft ready. Some tasks need input first.");
      ctx.refresh();
    } catch (err) { showError(err); }
  });
  root.querySelector("#generate")?.addEventListener("click", (e) => generate(e.currentTarget));
  root.querySelector("#generate-banner")?.addEventListener("click", (e) => generate(e.currentTarget));

  root.querySelector("#adopt")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      await api.post(`/api/plans/${draft.plan_id}/adopt`, { based_on: draft.based_on });
      draft = null;
      toast("Plan saved. Export it to your calendar any time.");
      ctx.refresh();
    } catch (err) {
      if (err.code === "STALE_DRAFT") {
        draft = null;
        toast("Something changed since this draft, so here is a fresh one.");
        ctx.go("plan", "replan=1");
      } else showError(err);
    }
  }));
  root.querySelector("#discard")?.addEventListener("click", () => { dismissedFor = draft?.based_on || null; draft = null; toast("Draft discarded. Your saved plan is unchanged."); ctx.refresh(); });
  root.querySelector("#export")?.addEventListener("click", async () => {
    try { await api.download("/api/plans/current/ics", "studyspace-plan.ics"); toast("Calendar file downloaded. Open it to add the sessions to Outlook, Google or Apple Calendar."); }
    catch (err) { showError(err); }
  });
  root.querySelector("#edit-hours").addEventListener("click", () => hoursDialog(ctx, settings, slots));
  root.querySelector("#edit-pace")?.addEventListener("click", () => hoursDialog(ctx, settings, slots));

  const planId = current?.plan_id;
  const actionsFor = (b, anchor) => {
    const task = taskById[b.task_id];
    const block = { ...b, plan_id: planId, title: task?.title, course_code: task?.course_code };
    if (draft) return toast("Adopt the plan first; then you can start, finish or move sessions.");
    if (b.done) return toast("This session is done.");
    const past = b.end <= now;
    menu(anchor, [
      ...(!past ? [{ label: "Start focus timer", icon: "play", onClick: () => openFocus(ctx, block, task) }] : []),
      { label: past ? "I did this session" : "Mark done", icon: "check", onClick: () => recordDone(ctx, block, task) },
      { label: b.locked ? "Unlock" : "Lock in place", hint: b.locked ? "" : "kept when you update the plan", icon: "lock", onClick: () => toggleLock(ctx, b) },
      { divider: true },
      { label: "Can't make it", hint: "find another time", icon: "ban", onClick: () => cantMakeIt(ctx, block) },
    ]);
  };
  root.querySelectorAll("[data-cand]").forEach((el) => el.addEventListener("click", async () => {
    const cands = await api.get("/api/candidates?status=pending");
    const c = cands.find((x) => x.candidate_id === el.dataset.cand);
    if (c) quickConfirm(ctx, c);
  }));
  root.querySelectorAll("[data-block]").forEach((el) => el.addEventListener("click", () => actionsFor(JSON.parse(el.dataset.block), el)));
  root.querySelectorAll("[data-more]").forEach((el) => el.addEventListener("click", () => actionsFor(JSON.parse(el.dataset.more), el)));
  root.querySelectorAll("[data-done-block]").forEach((el) => el.addEventListener("click", () => {
    const b = JSON.parse(el.dataset.doneBlock);
    recordDone(ctx, { ...b, plan_id: planId }, taskById[b.task_id]);
  }));
  root.querySelectorAll("[data-focus-block]").forEach((el) => el.addEventListener("click", () => {
    const b = JSON.parse(el.dataset.focusBlock);
    openFocus(ctx, { ...b, plan_id: planId }, taskById[b.task_id]);
  }));
}

async function toggleLock(ctx, b) {
  try {
    await api.post("/api/plans/lock", { task_id: b.task_id, start: b.start, end: b.end, locked: !b.locked });
    toast(b.locked ? "Unlocked." : "Locked. Updating the plan keeps this session where it is.");
    ctx.refresh();
  } catch (err) { showError(err); }
}

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

async function hoursDialog(ctx, settings, slots) {
  const template = (await api.get("/api/calendar/template")) || { from: sgDate(ctx.workspace.now), to: addDays(sgDate(ctx.workspace.now), 34), weekly: [] };
  const p = settings.plan;
  const fixed = slots.filter((s) => s.kind === "busy" && s.origin === "manual").sort((a, b) => a.start.localeCompare(b.start));
  const dayRows = WEEKDAYS.map((wd) => {
    const ranges = template.weekly.filter((w) => w.weekday === wd);
    return `<div class="row" data-day="${wd}" style="align-items:flex-start">
      <b style="width:90px;font-size:12.5px;padding-top:7px">${wd[0].toUpperCase() + wd.slice(1, 3)}</b>
      <div class="stack" style="gap:6px;flex:1" data-ranges>${ranges.map(rangeRow).join("")}</div>
      <button class="btn tiny ghost" data-add-range style="margin-top:4px">+ add</button></div>`;
  }).join("");
  await modal("Your hours", `
    <p class="small muted" style="margin:0">When are you willing to study? Studyspace only plans inside these hours, never over classes or meetings.</p>
    <div class="form-grid">
      <label class="field">From <input type="date" id="h-from" value="${esc(template.from)}"></label>
      <label class="field">To <input type="date" id="h-to" value="${esc(template.to)}"></label>
    </div>
    <div class="stack" style="gap:10px" id="h-days">${dayRows}</div>
    <p class="side-title" style="margin:8px 0 0">Pace</p>
    <div class="form-grid">
      <label class="field">Daily focus limit · h <input type="number" id="p-daily" min="0.5" max="12" step="0.5" value="${hours(p.max_study_minutes_per_day)}"></label>
      <label class="field">Preferred buffer · h <input type="number" id="p-buffer" min="0" max="168" step="1" value="${hours(p.target_buffer_minutes)}"></label>
      <label class="field">Earliest study time <input type="time" id="p-start" value="${esc(p.study_day_start)}"></label>
      <label class="field">Latest study time <input type="time" id="p-end" value="${esc(p.study_day_end)}"></label>
    </div>
    <p class="side-title" style="margin:8px 0 0">Fixed commitments you added</p>
    <div class="stack" style="gap:6px" id="h-fixed">${fixed.length ? fixed.map((s) => `<div class="row between small"><span>${esc(s.label || "Busy")} · ${esc(fmtDateTime(s.start))}–${esc(fmtRange(s.start, s.end).split("–")[1])}</span><button class="btn tiny danger" data-del-slot="${esc(s.slot_id)}">Remove</button></div>`).join("") : `<span class="small muted">None. Add meetings from “Find a meeting time”, or below.</span>`}</div>
    <div class="form-grid">
      <label class="field">Commitment <input type="text" id="b-label" placeholder="e.g. Part-time work"></label>
      <label class="field">Day <input type="date" id="b-day" value="${esc(sgDate(ctx.workspace.now))}"></label>
      <label class="field">Start <input type="time" id="b-start" value="14:00"></label>
      <label class="field">End <input type="time" id="b-end" value="16:00"></label>
    </div>
    <div><button class="btn small" id="b-add">+ Add commitment</button></div>`, {
    wide: true,
    actions: [{ label: "Cancel", value: null }, {
      label: "Save hours", primary: true, onClick: async (dlg) => {
        const weekly = [];
        dlg.querySelectorAll("[data-day]").forEach((row) => row.querySelectorAll("[data-range]").forEach((r) => {
          const [s, e] = r.querySelectorAll("input");
          if (s.value && e.value && e.value > s.value) weekly.push({ weekday: row.dataset.day, start: s.value, end: e.value });
        }));
        await api.put("/api/calendar/availability", { template: { from: dlg.querySelector("#h-from").value, to: dlg.querySelector("#h-to").value, weekly } });
        await api.put("/api/settings", { plan: {
          ...p, max_study_minutes_per_day: Math.round(parseFloat(dlg.querySelector("#p-daily").value) * 60),
          target_buffer_minutes: Math.round(parseFloat(dlg.querySelector("#p-buffer").value) * 60),
          study_day_start: dlg.querySelector("#p-start").value, study_day_end: dlg.querySelector("#p-end").value,
        } });
        toast("Hours saved. Re-plan to use them.");
        ctx.refresh();
      },
    }],
  });
}

function rangeRow(r = { start: "09:00", end: "12:00" }) {
  return `<div class="row" data-range><input type="time" class="compact" style="width:110px" value="${esc(r.start)}" aria-label="From"><span class="muted">to</span><input type="time" class="compact" style="width:110px" value="${esc(r.end)}" aria-label="To"><button class="btn tiny ghost" data-remove-range aria-label="Remove">✕</button></div>`;
}

document.addEventListener("click", async (e) => {
  const dlg = e.target.closest("dialog");
  if (!dlg) return;
  if (e.target.closest("[data-add-range]")) {
    e.target.closest("[data-day]").querySelector("[data-ranges]").insertAdjacentHTML("beforeend", rangeRow());
  } else if (e.target.closest("[data-remove-range]")) {
    e.target.closest("[data-range]").remove();
  } else if (e.target.closest("[data-del-slot]")) {
    const btn = e.target.closest("[data-del-slot]");
    try { await api.del(`/api/calendar/slots/${encodeURIComponent(btn.dataset.delSlot)}`); btn.closest(".row").remove(); toast("Removed. Re-plan to use the freed time."); }
    catch (err) { showError(err); }
  } else if (e.target.closest("#b-add")) {
    const day = dlg.querySelector("#b-day").value, s = dlg.querySelector("#b-start").value, en = dlg.querySelector("#b-end").value;
    if (!day || !s || !en || en <= s) return toast("Choose a day and a start before the end.", "error");
    try {
      await api.post("/api/calendar/busy", { start: `${day}T${s}:00+08:00`, end: `${day}T${en}:00+08:00`, label: dlg.querySelector("#b-label").value || "Busy" });
      dlg.querySelector("#h-fixed").insertAdjacentHTML("beforeend", `<div class="row between small"><span>${esc(dlg.querySelector("#b-label").value || "Busy")} · ${esc(day)} ${esc(s)}–${esc(en)}</span><span class="chip green">added</span></div>`);
      toast("Commitment added.");
    } catch (err) { showError(err); }
  }
});
