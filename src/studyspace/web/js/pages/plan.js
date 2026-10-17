// 03 Study plan (gate 2): a draft replaces nothing until the student adopts it.
import { api } from "../api.js";
import {
  WARNING_TEXT, addDays, busy, courseColorClass, esc, fmtDate, fmtDateTime, fmtRange, hours, minutesBetween, modal, mondayOf,
  sgDate, sgParts, showError, toast,
} from "../util.js";

const DAY_START = 8, DAY_END = 22, PX_PER_HOUR = 40;
let draft = null;     // POST /api/plans/draft response, kept until adopted or discarded
let weekStart = null;
let view = null;

export async function render(root, ctx) {
  const [current, tasks, slots, settings] = await Promise.all([
    api.get("/api/plans/current"), api.get("/api/tasks"), api.get("/api/calendar"), api.get("/api/settings"),
  ]);
  const now = ctx.workspace.now;
  if (!weekStart) weekStart = mondayOf(sgDate(now));
  if (!view) view = window.matchMedia("(max-width: 820px)").matches ? "list" : "week";
  const taskById = Object.fromEntries(tasks.map((t) => [t.task_id, t]));
  const openTasks = tasks.filter((t) => t.status === "open");
  const showing = draft ? "draft" : current ? "saved" : "none";
  const result = draft ? draft.result : current?.result;
  const blocks = draft ? draftBlocks(draft, current) : current?.blocks || [];
  const weekEnd = addDays(weekStart, 6);
  const inWeek = (iso) => { const d = sgDate(iso); return d >= weekStart && d <= weekEnd; };
  const weekBlocks = blocks.filter((b) => inWeek(b.start));

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Make room for focus</p>
        <h1>Your week, with room to breathe.</h1>
        <p class="lede">A realistic draft inside the hours you choose: never past a deadline, never more than your daily limit.</p>
      </div>
      <span class="step-tag">STEP 03 OF 03</span>
    </div>
    ${notices(showing, current, draft, openTasks)}
    <div class="row between" style="margin-bottom:14px">
      <div class="week-nav">
        <button class="btn small" data-week="-1" aria-label="Previous week">‹</button>
        <h2>${esc(fmtDate(weekStart + "T12:00:00+08:00"))} – ${esc(fmtDate(weekEnd + "T12:00:00+08:00"))} ${esc(weekStart.slice(0, 4))}</h2>
        <button class="btn small" data-week="1" aria-label="Next week">›</button>
        <button class="btn small ghost" data-week="0">This week</button>
      </div>
      <div class="row">
        ${statusPill(showing, current)}
        <div class="tabs"><button data-view="week" class="${view === "week" ? "active" : ""}">Week</button><button data-view="list" class="${view === "list" ? "active" : ""}">List</button></div>
        <button class="btn small" id="edit-hours">Edit hours</button>
        ${current && !draft ? `<button class="btn small" id="export">Export .ics</button>` : ""}
        <button class="btn small primary" id="generate">${current || draft ? "Re-plan" : "Generate plan"}</button>
      </div>
    </div>
    <div class="grid">
      <div class="stack">
        <section class="card">
          <div class="card-head">
            <h2>${showing === "draft" ? "Proposed study sessions" : showing === "saved" ? "Saved study sessions" : "Study sessions"}</h2>
            <div class="legend"><span><i style="background:color-mix(in srgb,var(--purple) 30%,var(--card))"></i>Study</span><span><i style="background:var(--busy)"></i>Class / meeting</span><span><i style="background:var(--amber-bg);border:1px solid var(--amber)"></i>Exam / event</span><span><i style="background:color-mix(in srgb,var(--green) 15%,transparent)"></i>Your free hours</span><span><i style="background:var(--red)"></i>Deadline</span></div>
          </div>
          ${showing === "none" && !openTasks.length ? `<div class="empty"><strong>Nothing to plan yet</strong>Confirm tasks first, then generate a plan.<div style="margin-top:14px"><a class="btn primary" href="#/review">Review tasks →</a></div></div>` : ""}
          ${view === "week" ? weekGrid(weekBlocks, slots, tasks, taskById, now, showing) : listView(weekBlocks, slots, tasks, taskById, now, showing)}
        </section>
        ${showing === "draft" ? `<div class="row between"><button class="btn" id="discard">Discard draft</button><span class="tiny muted">Preview before replacing your saved plan.</span><button class="btn primary" id="adopt">Adopt and save</button></div>` : ""}
      </div>
      <aside class="stack">${sidePanel(result, blocks, weekBlocks, openTasks, taskById, settings, current, showing)}</aside>
    </div>`;

  bind(root, ctx, { current, taskById, settings, slots, now });
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
  if (showing === "saved") return current.replan_reasons.length ? `<span class="chip amber">Saved · may be out of date</span>` : `<span class="chip green">Saved plan</span>`;
  return `<span class="chip outline">No plan yet</span>`;
}

function notices(showing, current, d, openTasks) {
  const out = [];
  if (showing === "draft") {
    const c = d.changes;
    out.push(`<div class="alert purple" style="margin-bottom:16px"><strong>This is a draft.</strong>
      <span>${c.had_saved_plan ? `Compared with your saved plan: ${c.added.length} new or moved session(s), ${c.removed.length} removed, ${c.kept} unchanged.` : "You have no saved plan yet."}
      Every session was checked against the rules (no clashes, daily limit, breaks, deadlines). Adopt it to save.</span></div>`);
  } else if (showing === "saved" && current.replan_reasons.length) {
    out.push(`<div class="alert amber" style="margin-bottom:16px"><strong>Your saved plan may no longer fit</strong><ul>${current.replan_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul><span>Re-plan to see a new draft. Locked and finished sessions stay where they are.</span></div>`);
  } else if (showing === "none" && openTasks.length) {
    out.push(`<div class="alert purple" style="margin-bottom:16px"><strong>${openTasks.length} confirmed task(s) ready.</strong><span>Generate a plan to see how they fit into your free hours.</span></div>`);
  }
  return out.join("");
}

function fixedItems(slots, tasks, start, end) {
  const busyItems = slots.filter((s) => s.kind === "busy" && s.end > start && s.start < end).map((s) => ({ ...s, type: "busy", title: s.label || "Busy" }));
  const events = tasks.filter((t) => t.kind === "event" && t.status === "open").map((t) => ({
    start: t.due_at, end: new Date(new Date(t.due_at).getTime() + (t.remaining_minutes || 60) * 60000).toISOString(), type: "event", title: t.title,
  })).filter((e) => e.end > start && e.start < end);
  return [...busyItems, ...events];
}

function weekGrid(blocks, slots, tasks, taskById, now, showing) {
  const days = [...Array(7)].map((_, i) => addDays(weekStart, i));
  const startIso = `${weekStart}T00:00:00+08:00`, endIso = `${addDays(weekStart, 7)}T00:00:00+08:00`;
  const fixed = fixedItems(slots, tasks, startIso, endIso);
  const free = slots.filter((s) => s.kind === "available" && s.end > startIso && s.start < endIso);
  const dues = tasks.filter((t) => t.kind === "deliverable" && t.status === "open" && t.due_at >= startIso && t.due_at < endIso);
  const top = (iso) => { const p = sgParts(iso); return Math.max(0, (p.h + p.min / 60 - DAY_START) * PX_PER_HOUR); };
  const height = (a, b) => Math.max(14, Math.min(minutesBetween(a, b) / 60, DAY_END - DAY_START) * PX_PER_HOUR);
  const today = sgDate(now);
  const colH = (DAY_END - DAY_START) * PX_PER_HOUR;
  const cols = days.map((d) => {
    const on = (iso) => sgDate(iso) === d;
    const inner = [
      ...free.filter((s) => on(s.start)).map((s) => `<div class="slot-bg" style="top:${top(s.start)}px;height:${height(s.start, s.end)}px"></div>`),
      ...fixed.filter((f) => on(f.start)).map((f) => `<div class="wg-block ${f.type}" style="top:${top(f.start)}px;height:${height(f.start, f.end)}px" title="${esc(f.title)} ${esc(fmtRange(f.start, f.end))}">${esc(f.title)}</div>`),
      ...blocks.filter((b) => on(b.start)).map((b) => {
        const t = taskById[b.task_id];
        return `<div class="wg-block study ${b.done ? "done" : ""} ${b.conflict ? "conflict" : ""}" style="top:${top(b.start)}px;height:${height(b.start, b.end)}px" title="${esc(t?.title || b.task_id)} ${esc(fmtRange(b.start, b.end))}">${b.locked ? "🔒 " : ""}${b.done ? "✓ " : ""}<b>${esc(t?.title || b.task_id)}</b><br>${esc(fmtRange(b.start, b.end))}</div>`;
      }),
      ...dues.filter((t) => on(t.due_at)).map((t) => `<div class="wg-due" style="top:${Math.min(colH - 2, top(t.due_at))}px" title="Due: ${esc(t.title)}"><span>Due: ${esc(t.title)}</span></div>`),
      d === today ? `<div class="wg-now" style="top:${top(now)}px"></div>` : "",
    ].join("");
    return `<div class="wg-col" style="height:${colH}px">${inner}</div>`;
  });
  const hourLabels = [...Array(DAY_END - DAY_START)].map((_, i) => `<div class="wg-hour">${String(DAY_START + i).padStart(2, "0")}:00</div>`).join("");
  return `<div class="table-wrap"><div class="week-grid">
    <div class="wg-head"></div>
    ${days.map((d) => { const p = sgParts(d + "T12:00:00+08:00"); return `<div class="wg-head ${d === today ? "today" : ""}">${p.weekday}<b>${p.d}</b></div>`; }).join("")}
    <div class="wg-hours">${hourLabels}</div>
    ${cols.join("")}
  </div></div>
  ${showing === "saved" ? `<div class="card-foot">Switch to List to lock a session or mark it done.</div>` : ""}`;
}

function listView(blocks, slots, tasks, taskById, now, showing) {
  const days = [...Array(7)].map((_, i) => addDays(weekStart, i));
  const startIso = `${weekStart}T00:00:00+08:00`, endIso = `${addDays(weekStart, 7)}T00:00:00+08:00`;
  const fixed = fixedItems(slots, tasks, startIso, endIso);
  const today = sgDate(now);
  const groups = days.map((d) => {
    const items = [
      ...blocks.filter((b) => sgDate(b.start) === d).map((b) => ({ kind: "study", ...b })),
      ...fixed.filter((f) => sgDate(f.start) === d).map((f) => ({ kind: f.type, ...f })),
    ].sort((a, b) => a.start.localeCompare(b.start));
    if (!items.length) return "";
    const p = sgParts(d + "T12:00:00+08:00");
    return `<div class="day-group"><div class="day-label ${d === today ? "today" : ""}">${p.weekday}<small>${esc(fmtDate(d + "T12:00:00+08:00"))}${d === today ? " · today" : ""}</small></div>
      <div class="sessions">${items.map((it) => it.kind === "study" ? sessionRow(it, taskById, showing, now) : `
        <div class="session ${it.kind === "event" ? "event" : "fixed"}"><span class="s-time">${esc(fmtRange(it.start, it.end))}</span><span><span class="s-title">${esc(it.title)}</span><div class="s-sub">${it.kind === "event" ? "exam or event" : "fixed"}</div></span><span></span></div>`).join("")}</div></div>`;
  }).join("");
  return groups || `<div class="empty">No sessions or classes this week.</div>`;
}

function sessionRow(b, taskById, showing, now) {
  const t = taskById[b.task_id];
  const past = b.end <= now;
  const actions = showing === "saved" && !b.done ? `
    <button class="btn tiny ${b.locked ? "on" : ""}" data-lock='${esc(JSON.stringify({ task_id: b.task_id, start: b.start, end: b.end, locked: !b.locked }))}'>${b.locked ? "Locked" : "Lock"}</button>
    <button class="btn tiny" data-done='${esc(JSON.stringify({ task_id: b.task_id, start: b.start, end: b.end }))}'>Done</button>` : b.done ? `<span class="chip green">Done</span>` : b.locked ? `<span class="chip">Locked</span>` : b.added ? `<span class="chip green">New</span>` : "";
  return `<div class="session ${courseColorClass(t?.course_code || b.task_id)} ${b.done ? "done" : ""} ${b.conflict ? "conflict" : ""} ${b.added ? "added" : ""}">
    <span class="s-time">${esc(fmtRange(b.start, b.end))}</span>
    <span><span class="s-title">${esc(t?.title || b.task_id)}</span><div class="s-sub">${esc(t?.course_code || "")}${t ? ` · due ${esc(fmtDateTime(t.due_at))}` : ""}${b.conflict ? " · clashes with a fixed commitment" : ""}${past && !b.done && showing === "saved" ? " · did it happen?" : ""}</div></span>
    <span class="s-actions">${actions}</span>
  </div>`;
}

function sidePanel(result, blocks, weekBlocks, openTasks, taskById, settings, current, showing) {
  const p = settings.plan;
  const weekMinutes = weekBlocks.filter((b) => !b.done).reduce((n, b) => n + minutesBetween(b.start, b.end), 0);
  const missing = (result?.unscheduled || []).reduce((n, u) => n + u.minutes, 0);
  const warnings = (result?.warnings || []);
  const results = result?.task_results || [];
  return `
  <section class="card glance"><div class="card-body">
    <p class="side-title">Your plan at a glance</p>
    <div class="big-number">${hours(weekMinutes)}<small>h</small></div>
    <p class="small" style="color:var(--green);margin:6px 0 14px">${showing === "none" ? "no plan yet" : "planned for focused work this week"}</p>
    <div class="kv"><span>Unassigned</span><b style="${missing ? "color:var(--red)" : ""}">${hours(missing)} h</b></div>
    <div class="kv"><span>Confirmed tasks</span><b>${openTasks.filter((t) => t.kind === "deliverable").length}</b></div>
    <div class="kv"><span>Locked sessions</span><b>${blocks.filter((b) => b.locked).length}</b></div>
  </div></section>
  ${warnings.length ? `<section class="card"><div class="card-body">
    <p class="side-title">Things to know</p>
    <div class="stack" style="gap:8px">${warnings.map((w) => `<div class="alert ${["INSUFFICIENT_TIME", "PAST_DEADLINE", "LOCK_CONFLICT"].includes(w.code) ? "red" : "amber"}"><strong>${esc(WARNING_TEXT[w.code] || w.code)}</strong><span>${esc(w.message)}</span></div>`).join("")}</div>
    ${missing ? `<p class="small muted" style="margin:10px 0 0">Add free hours, lower an estimate, or talk to the course team. Studyspace never squeezes work into the night or past a deadline.</p>` : ""}
  </div></section>` : ""}
  ${results.length ? `<section class="card"><div class="card-body">
    <p class="side-title">Task coverage</p>
    ${results.map((r) => {
      const t = taskById[r.task_id];
      const planned = r.scheduled_minutes + r.locked_future_minutes;
      const pct = r.reserved_minutes ? Math.round((planned / r.reserved_minutes) * 100) : 100;
      return `<div class="task-line"><div class="row between"><b>${esc(t?.title || r.task_id)}</b><span class="tiny muted">${hours(planned)} / ${hours(r.reserved_minutes)} h</span></div>
        <div class="bar"><span style="width:${Math.min(100, pct)}%;${pct < 100 ? "background:var(--red)" : ""}"></span></div></div>`;
    }).join("")}
  </div></section>` : ""}
  <section class="card"><div class="card-body">
    <p class="side-title">A sustainable pace</p>
    <div class="kv" style="border-top:0"><span>Daily focus limit</span><b>${hours(p.max_study_minutes_per_day)} h</b></div>
    <div class="kv"><span>Longest session</span><b>${p.max_block_minutes} min</b></div>
    <div class="kv"><span>Break between sessions</span><b>${p.min_break_minutes} min</b></div>
    <div class="kv"><span>Preferred buffer</span><b>${hours(p.target_buffer_minutes)} h</b></div>
    <p class="tiny muted" style="margin:8px 0 0">Work stays within ${esc(p.study_day_start)}–${esc(p.study_day_end)} and your available hours. A buffer warning stays visible.</p>
  </div></section>
  <section class="card soft"><div class="card-body">
    <p class="side-title">A plan you can change</p>
    <p class="small muted" style="margin:0">Lock a session to keep its time when you re-plan. Mark it done to count the work. Changed deadlines and hours need a new preview.</p>
  </div></section>`;
}

function bind(root, ctx, { current, taskById, settings, slots, now }) {
  root.querySelectorAll("[data-week]").forEach((b) => b.addEventListener("click", () => {
    const step = +b.dataset.week;
    weekStart = step === 0 ? mondayOf(sgDate(now)) : addDays(weekStart, step * 7);
    ctx.refresh();
  }));
  root.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => { view = b.dataset.view; ctx.refresh(); }));

  root.querySelector("#generate").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      draft = await api.post("/api/plans/draft", {});
      const r = draft.result;
      toast(r.status === "complete" ? "Draft ready. Every task fits." : r.status === "partial" ? "Draft ready, but some work does not fit. See the warnings." : "Draft ready. Some tasks need input first.");
      ctx.refresh();
    } catch (err) { showError(err); }
  }));

  root.querySelector("#adopt")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      await api.post(`/api/plans/${draft.plan_id}/adopt`, { based_on: draft.based_on });
      draft = null;
      toast("Plan saved. You can export it to your calendar.");
      ctx.refresh();
    } catch (err) {
      if (err.code === "STALE_DRAFT") {
        draft = null;
        toast("Your tasks or hours changed since this draft. Generate a new one.", "error");
        ctx.refresh();
      } else showError(err);
    }
  }));
  root.querySelector("#discard")?.addEventListener("click", () => { draft = null; ctx.refresh(); });
  root.querySelector("#export")?.addEventListener("click", async () => {
    try { await api.download("/api/plans/current/ics", "studyspace-plan.ics"); toast("Calendar file downloaded. Open it to add the sessions to Outlook, Google or Apple Calendar."); }
    catch (err) { showError(err); }
  });
  root.querySelector("#edit-hours").addEventListener("click", () => hoursDialog(ctx, settings, slots));

  root.querySelectorAll("[data-lock]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const body = JSON.parse(b.dataset.lock);
      await api.post("/api/plans/lock", body);
      toast(body.locked ? "Locked. Re-planning keeps this session where it is." : "Unlocked.");
      ctx.refresh();
    } catch (err) { showError(err); }
  }));
  root.querySelectorAll("[data-done]").forEach((b) => b.addEventListener("click", () => doneDialog(ctx, JSON.parse(b.dataset.done), taskById, current)));
}

async function doneDialog(ctx, block, taskById, current) {
  const t = taskById[block.task_id];
  const mins = minutesBetween(block.start, block.end);
  const left = Math.max(0, (t?.remaining_minutes || 0) - mins);
  await modal("Session done", `
    <p style="margin:0"><b>${esc(t?.title || block.task_id)}</b><br><span class="muted small">${esc(fmtDateTime(block.start))} – ${esc(fmtRange(block.start, block.end).split("–")[1])} · ${hours(mins)} h</span></p>
    <label class="field">How much work is left on this task? (hours)
      <input type="number" id="left" min="0" step="0.25" value="${hours(left)}">
      <span class="hint">Change it if the session went faster or slower than planned. 0 marks the task done.</span>
    </label>`, {
    actions: [{ label: "Cancel", value: null }, {
      label: "Record", primary: true, onClick: async (dlg) => {
        const leftMin = Math.round(parseFloat(dlg.querySelector("#left").value || "0") * 60);
        const r = await api.post("/api/progress", {
          op_id: `${current.plan_id}:${block.task_id}:${block.start}`, task_id: block.task_id, start: block.start, end: block.end, remaining_minutes: leftMin,
        });
        toast(r.recorded ? (r.task.status === "done" ? "Nice work. Task finished." : `Recorded. ${hours(r.task.remaining_minutes)} h left.`) : "Already recorded.");
        ctx.refresh();
      },
    }],
  });
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
      <button class="btn tiny" data-add-range style="margin-top:4px">+ add</button></div>`;
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
