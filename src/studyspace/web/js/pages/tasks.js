// Tasks (gate 1): grouped by what each one needs from the student, confirmed in one click each.
import { api } from "../api.js";
import { EFFORT_CHOICES, confirmCandidate, dismissCandidate } from "../actions.js";
import { icon } from "../icons.js";
import { openSource } from "../sources-common.js";
import {
  FLAG_TEXT, busy, courseIndex, courseTag, dueLabel, esc, flagChips, fmtDateTime, fmtMinutes, fromLocalInput, fromNow, minutesBetween,
  modal, senderName, showError, toLocalInput, toast, urgency,
} from "../util.js";

let tab = "check";
const state = {};   // candidate_id -> {due, minutes, priority, title, open}

export async function render(root, ctx, params) {
  const [cands, tasks, sources, plan] = await Promise.all([
    api.get("/api/candidates"), api.get("/api/tasks"), api.get("/api/sources"), api.get("/api/plans/current"),
  ]);
  const now = ctx.workspace.now;
  const pending = cands.filter((c) => c.status === "pending");
  const open = tasks.filter((t) => t.status === "open");
  const done = tasks.filter((t) => t.status === "done");
  const src = Object.fromEntries(sources.map((s) => [s.record_id, s]));
  const byTask = Object.fromEntries(tasks.map((t) => [t.task_id, t]));
  if (params.get("tab")) tab = params.get("tab");
  if (params.get("focus") || params.get("section")) tab = "check";

  for (const c of pending) {
    state[c.candidate_id] ||= {
      due: c.due_at && !c.flags.includes("MIDNIGHT_AMBIGUITY") ? c.due_at : null,
      minutes: c.suggested_minutes, priority: "medium", title: c.title, open: false,
    };
  }
  const groups = group(pending, now, byTask);

  root.innerHTML = `
    <div class="page-head">
      <div><h1>Tasks</h1><p class="lede">Found in your messages and files. Confirm the deadline and effort, and it goes into your plan.</p></div>
      <button class="btn small" id="add-task">${icon("plus", 15)} Add a task</button>
    </div>
    <div class="tabs page-tabs" role="tablist">
      <button data-tab="check" class="${tab === "check" ? "active" : ""}">To check <span class="n">${pending.length}</span></button>
      <button data-tab="open" class="${tab === "open" ? "active" : ""}">Confirmed <span class="n">${open.length}</span></button>
      <button data-tab="done" class="${tab === "done" ? "active" : ""}">Done <span class="n">${done.length}</span></button>
    </div>
    <div id="tab-body"></div>`;

  const body = root.querySelector("#tab-body");
  if (tab === "check") renderCheck(body, ctx, groups, src, byTask, now, params);
  else renderTasks(body, ctx, tab === "open" ? open : done, plan, now, tab);

  // confirmed work that the saved plan does not cover yet: one click to see it placed on the calendar
  const inPlan = new Set((plan?.blocks || []).map((b) => b.task_id));
  const unplanned = open.filter((t) => t.kind === "deliverable" && t.remaining_minutes > 0 && t.due_at > now && !inPlan.has(t.task_id));
  if (unplanned.length) {
    root.insertAdjacentHTML("beforeend", `<div class="plan-bar"><span class="attn-icon purple">${icon("calendar", 16)}</span>
      <span><b>${unplanned.length} confirmed task${unplanned.length === 1 ? " isn't" : "s aren't"} in your plan yet</b><span class="tiny muted">${esc(unplanned.slice(0, 3).map((t) => t.title).join(", "))}${unplanned.length > 3 ? "…" : ""}</span></span>
      <a class="btn small primary" href="#/plan">See them on the calendar ${icon("arrow", 14)}</a></div>`);
  }

  root.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; ctx.go("tasks"); ctx.refresh(); }));
  root.querySelector("#add-task").addEventListener("click", () => addTaskDialog(ctx));
}

function group(pending, now, byTask) {
  const today = now.slice(0, 10);
  const g = { decide: [], ready: [], undated: [], past: [] };
  for (const c of pending) {
    const past = (c.due_at && c.due_at < now) || (!c.due_at && c.due_date && c.due_date < today);
    if (past) g.past.push(c);
    else if (c.related_task_id && byTask[c.related_task_id]) g.decide.push(c);
    else if (c.due_at && !c.flags.includes("MIDNIGHT_AMBIGUITY")) g.ready.push(c);
    else if (c.due_options.length || c.due_date) g.decide.push(c);
    else g.undated.push(c);
  }
  const when = (c) => c.due_at || (c.due_date ? `${c.due_date}T23:59` : "9999");
  Object.values(g).forEach((list) => list.sort((a, b) => when(a).localeCompare(when(b))));
  return g;
}

// ---- to check ---------------------------------------------------------------------------------
function renderCheck(body, ctx, g, src, byTask, now, params) {
  const total = g.decide.length + g.ready.length + g.undated.length + g.past.length;
  if (!total) {
    body.innerHTML = `<section class="card"><div class="calm big">${icon("check", 28)}<div><b>All caught up</b><span>New tasks appear here when Studyspace reads new messages or files.</span></div>
      <a class="btn primary" href="#/plan">Open your plan</a></div></section>`;
    return;
  }
  const section = (key, title, hint, list, extra = "") => list.length ? `
    <section class="task-section" data-section="${key}">
      <div class="section-head"><div><h2>${title} <span class="n">${list.length}</span></h2><p>${hint}</p></div>${extra}</div>
      <div class="task-list">${list.map((c) => card(c, key, src, byTask, now)).join("")}</div>
    </section>` : "";
  body.innerHTML = `
    ${section("decide", "Needs your decision", "The message leaves something open: pick the deadline that is meant.", g.decide)}
    ${section("ready", "Ready to confirm", "Dates are clear. Check the suggested effort and confirm.", g.ready,
      g.ready.length > 1 ? `<button class="btn small primary" id="confirm-all">Confirm all ${g.ready.length}</button>` : "")}
    ${section("undated", "No deadline in the message", "Add a date and time so they can be planned, or set them aside.", g.undated)}
    ${section("past", "Deadline already passed", "Mark them done, or give a new date if they still need work.", g.past)}
    <p class="kbd-hint">${icon("spark", 14)} Keyboard: <kbd>J</kbd>/<kbd>K</kbd> move · <kbd>Enter</kbd> confirm · <kbd>X</kbd> set aside · <kbd>W</kbd> why</p>`;
  bindCheck(body, ctx, g, src, byTask, now);
  const focus = params.get("focus") ? body.querySelector(`[data-card="${CSS.escape(params.get("focus"))}"]`) : params.get("section") ? body.querySelector(`[data-section="${CSS.escape(params.get("section"))}"] .task-card`) : null;
  if (focus) { focus.scrollIntoView({ block: "center" }); focus.focus(); focus.classList.add("flash"); }
}

function card(c, key, src, byTask, now) {
  const s = state[c.candidate_id];
  const latest = src[c.source_ids[c.source_ids.length - 1]];
  const sourceName = latest ? (latest.source_type === "pdf" ? latest.subject : senderName(latest.sender)) : "";
  const related = c.related_task_id ? byTask[c.related_task_id] : null;
  const dueChip = s.due ? `<span class="chip ${urgency(s.due, now)}" title="${esc(fmtDateTime(s.due))}">${esc(dueLabel(s.due, now))} · ${esc(fromNow(s.due, now))}</span>`
    : `<span class="chip outline">no time yet</span>`;
  let decision = "";
  if (related) {
    decision = `<div class="decision"><span class="decision-q">${icon("sync", 14)} Updates your task “${esc(related.title)}”: ${esc(fmtDateTime(related.due_at))} → <b>${esc(c.due_at ? fmtDateTime(c.due_at) : c.due_text || "?")}</b></span>
      <div class="seg"><button class="seg-btn on" data-use-new>Use the new date</button><button class="seg-btn" data-keep-old>Keep the current date</button></div></div>`;
  } else if (key === "decide") {
    const opts = c.due_options.length
      ? c.due_options.map((o) => [o, `${dueLabel(o, now)}${o.endsWith("T00:00:00+08:00") ? " (start of day)" : o.includes("T23:59") ? " (end of day)" : ""}`])
      : ["09:00", "12:00", "17:00", "23:59"].map((h) => [`${c.due_date}T${h}:00+08:00`, h]);
    const q = c.flags.includes("MIDNIGHT_AMBIGUITY") ? "“12 midnight” — start or end of the day?" : c.due_options.length ? "Due before an exam in the same message. When exactly?" : `“${c.due_text || c.due_date}” — which time?`;
    decision = `<div class="decision"><span class="decision-q">${icon("clock", 14)} ${esc(q)}</span>
      <div class="seg" data-due-seg>${opts.map(([v, l]) => `<button class="seg-btn ${s.due === v ? "on" : ""}" data-due="${esc(v)}">${esc(l)}</button>`).join("")}
      <input type="datetime-local" class="compact seg-input" data-due-input value="${esc(toLocalInput(s.due && !opts.some(([v]) => v === s.due) ? s.due : ""))}" aria-label="Other date and time"></div></div>`;
  } else if (key === "undated" || key === "past") {
    decision = `<div class="decision"><span class="decision-q">${icon("calendar", 14)} ${key === "past" ? `Was due ${esc(c.due_at ? fmtDateTime(c.due_at) : c.due_date)}. Still to do? Give a new deadline:` : esc(c.due_text ? `The message says “${c.due_text}”. Pick the exact deadline:` : "The message gives no deadline. When is it due?")}</span>
      <div class="seg"><input type="datetime-local" class="compact" data-due-input value="${esc(toLocalInput(s.due || ""))}" aria-label="Deadline"></div></div>`;
  }
  const isEvent = c.kind === "event";
  const choices = isEvent ? [60, 90, 120, 180] : EFFORT_CHOICES;
  const custom = s.minutes != null && !choices.includes(s.minutes);
  return `
  <article class="task-card k${courseIndex(c.course_code)} ${s.open ? "open" : ""}" tabindex="0" data-card="${esc(c.candidate_id)}" aria-label="${esc(c.title)}">
    <div class="tc-top">
      <input class="title-edit" value="${esc(s.title)}" aria-label="Task title" data-title>
      ${dueChip}
    </div>
    <div class="tc-meta">${courseTag(c.course_code)}${isEvent ? `<span class="chip blue">Event</span>` : ""}${flagChips(c.flags.filter((f) => f !== "NEEDS_CONFIRM" || key === "ready"))}
      ${sourceName ? `<button class="link-btn" data-source="${esc(latest.record_id)}">${icon(latest.source_type === "pdf" ? "file" : "mail", 13)} ${esc(sourceName)}${c.source_ids.length > 1 ? ` +${c.source_ids.length - 1}` : ""}</button>` : ""}
      <button class="link-btn" data-why>${s.open ? "Hide why" : "Why?"}</button></div>
    <div class="tc-why" ${s.open ? "" : "hidden"}>
      <div class="quote">${esc(c.evidence)}</div>
      ${c.due_text ? `<p class="small muted">Deadline as written: <b>“${esc(c.due_text)}”</b></p>` : ""}
      ${c.flags.map((f) => `<p class="small muted">${flagChips([f])} ${esc((FLAG_TEXT[f] || [, , f])[2])}</p>`).join("")}
      ${c.history.length ? `<ul class="history">${c.history.map((h) => `<li><s>${esc(h.due_at ? fmtDateTime(h.due_at) : h.due_date || "no date")}</s><span>earlier message</span></li>`).join("")}</ul>` : ""}
    </div>
    ${decision}
    ${key === "past" && !s.due ? "" : `
    <div class="tc-effort">
      <span class="tc-label">${isEvent ? "Length" : "Effort"}</span>
      <div class="seg small" data-min-seg>${choices.map((m) => `<button class="seg-btn ${s.minutes === m ? "on" : ""} ${m === c.suggested_minutes ? "suggested" : ""}" data-min="${m}" title="${m === c.suggested_minutes ? "suggested" : ""}">${esc(fmtMinutes(m).replace(" min", "m").replace(" h", "h"))}</button>`).join("")}
        <input type="number" class="compact seg-input num" min="0.25" step="0.25" placeholder="h" value="${custom ? s.minutes / 60 : ""}" data-min-input aria-label="Other effort in hours"></div>
      <button class="prio ${s.priority === "high" ? "on" : ""}" data-prio title="High priority">${icon("flag", 14)}</button>
    </div>`}
    <div class="tc-actions">
      ${key === "past" ? `<button class="btn small" data-done-already>Already done</button>` : `<button class="btn small ghost" data-dismiss>Not a task</button>`}
      ${related ? "" : `<button class="btn small primary" data-confirm>${icon("check", 15)} Confirm</button>`}
    </div>
  </article>`;
}

function bindCheck(body, ctx, g, src, byTask, now) {
  const all = [...g.decide, ...g.ready, ...g.undated, ...g.past];
  const find = (id) => all.find((c) => c.candidate_id === id);
  body.querySelectorAll("[data-card]").forEach((el) => {
    const c = find(el.dataset.card);
    const s = state[c.candidate_id];
    const refreshDue = () => {
      const chip = el.querySelector(".tc-top .chip");
      chip.outerHTML = s.due ? `<span class="chip ${urgency(s.due, now)}">${esc(dueLabel(s.due, now))} · ${esc(fromNow(s.due, now))}</span>` : `<span class="chip outline">no time yet</span>`;
    };
    el.querySelector("[data-title]").addEventListener("input", (e) => (s.title = e.target.value));
    el.querySelector("[data-why]").addEventListener("click", () => {
      s.open = !s.open;
      el.querySelector(".tc-why").hidden = !s.open;
      el.querySelector("[data-why]").textContent = s.open ? "Hide why" : "Why?";
    });
    el.querySelector("[data-source]")?.addEventListener("click", () => openSource(el.querySelector("[data-source]").dataset.source, ctx));
    el.querySelector("[data-due-seg]")?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-due]");
      if (!b) return;
      s.due = b.dataset.due;
      el.querySelectorAll("[data-due]").forEach((x) => x.classList.toggle("on", x === b));
      const inp = el.querySelector("[data-due-input]");
      if (inp) inp.value = "";
      refreshDue();
    });
    el.querySelector("[data-due-input]")?.addEventListener("change", (e) => {
      s.due = fromLocalInput(e.target.value);
      el.querySelectorAll("[data-due]").forEach((x) => x.classList.remove("on"));
      refreshDue();
    });
    el.querySelector("[data-min-seg]")?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-min]");
      if (!b) return;
      s.minutes = +b.dataset.min;
      el.querySelectorAll("[data-min]").forEach((x) => x.classList.toggle("on", x === b));
      el.querySelector("[data-min-input]").value = "";
    });
    el.querySelector("[data-min-input]")?.addEventListener("input", (e) => {
      const v = parseFloat(e.target.value);
      s.minutes = v > 0 ? Math.round(v * 60) : null;
      el.querySelectorAll("[data-min]").forEach((x) => x.classList.remove("on"));
    });
    el.querySelector("[data-prio]")?.addEventListener("click", (e) => {
      s.priority = s.priority === "high" ? "medium" : "high";
      e.currentTarget.classList.toggle("on", s.priority === "high");
    });
    el.querySelector("[data-confirm]")?.addEventListener("click", () => doConfirm(el, c, s, ctx));
    el.querySelector("[data-use-new]")?.addEventListener("click", () => doConfirm(el, c, { ...s, due: c.due_at || s.due }, ctx));
    el.querySelector("[data-keep-old]")?.addEventListener("click", () => leave(el, () => dismissCandidate(ctx, c)));
    el.querySelector("[data-dismiss]")?.addEventListener("click", () => leave(el, () => dismissCandidate(ctx, c)));
    el.querySelector("[data-done-already]")?.addEventListener("click", () => leave(el, () => dismissCandidate(ctx, c)));
  });

  body.querySelector("#confirm-all")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const ids = [];
    for (const c of g.ready) {
      const s = state[c.candidate_id];
      if (!s.minutes) continue;
      try {
        await api.post(`/api/candidates/${encodeURIComponent(c.candidate_id)}/confirm`, { due_at: s.due, remaining_minutes: s.minutes, priority: s.priority, ...(s.title !== c.title ? { title: s.title } : {}) });
        ids.push(c.candidate_id);
      } catch (err) { showError(err); }
    }
    toast(`Confirmed ${ids.length} task${ids.length === 1 ? "" : "s"}.`, "info", {
      label: "Undo", onClick: async () => { for (const id of ids) await api.post(`/api/candidates/${encodeURIComponent(id)}/restore`); toast("Back in your list."); ctx.refresh(); },
    });
    ctx.refresh();
  }));

  // keyboard: J/K to move, Enter to confirm, X to set aside, W for why
  const cards = () => [...body.querySelectorAll("[data-card]")];
  body.onkeydown = (e) => {
    if (e.target.matches("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const list = cards();
    const cur = e.target.closest("[data-card]");
    const i = list.indexOf(cur);
    const k = e.key.toLowerCase();
    if (k === "j" || e.key === "ArrowDown") { e.preventDefault(); list[Math.min(list.length - 1, i + 1)]?.focus(); }
    else if (k === "k" || e.key === "ArrowUp") { e.preventDefault(); list[Math.max(0, i - 1)]?.focus(); }
    else if (cur && e.key === "Enter" && e.target === cur) { e.preventDefault(); cur.querySelector("[data-confirm], [data-use-new]")?.click(); }
    else if (cur && k === "x") { e.preventDefault(); cur.querySelector("[data-dismiss], [data-keep-old], [data-done-already]")?.click(); }
    else if (cur && k === "w") { e.preventDefault(); cur.querySelector("[data-why]")?.click(); }
  };
}

async function doConfirm(el, c, s, ctx) {
  if (!s.due) { el.querySelector(".decision")?.classList.add("shake"); setTimeout(() => el.querySelector(".decision")?.classList.remove("shake"), 500); return toast("Pick the deadline first.", "error"); }
  if (!s.minutes && c.kind !== "event") { el.querySelector(".tc-effort")?.classList.add("shake"); setTimeout(() => el.querySelector(".tc-effort")?.classList.remove("shake"), 500); return toast("How long will it take? Pick an effort.", "error"); }
  await leave(el, () => confirmCandidate(ctx, c, { due_at: s.due, minutes: s.minutes ?? 60, priority: s.priority, title: s.title }, false));
  ctx.refresh();
}

async function leave(el, fn) {
  el.classList.add("leaving");
  try { await fn(); } catch (err) { el.classList.remove("leaving"); showError(err); throw err; }
}

// ---- confirmed and done -------------------------------------------------------------------------
function renderTasks(body, ctx, list, plan, now, which) {
  if (!list.length) {
    body.innerHTML = `<section class="card"><div class="calm big">${icon(which === "open" ? "calendar" : "check", 28)}<div><b>${which === "open" ? "No confirmed tasks yet" : "Nothing finished yet"}</b><span>${which === "open" ? "Confirm tasks from “To check” and they appear here." : "Finished tasks are kept here."}</span></div></div></section>`;
    return;
  }
  const planned = {};
  for (const b of plan?.blocks || []) if (!b.done && b.end > now) planned[b.task_id] = (planned[b.task_id] || 0) + minutesBetween(b.start, b.end);
  const sorted = [...list].sort((a, b) => a.due_at.localeCompare(b.due_at));
  body.innerHTML = `<section class="card"><div class="task-rows">${sorted.map((t) => {
    const p = planned[t.task_id] || 0;
    const pct = t.remaining_minutes ? Math.min(100, Math.round((p / t.remaining_minutes) * 100)) : 100;
    return `<div class="task-row k${courseIndex(t.course_code)}" data-task="${esc(t.task_id)}">
      <div class="tr-main"><b>${esc(t.title)}</b><span>${courseTag(t.course_code)}${t.kind === "event" ? `<span class="chip blue">Event</span>` : ""}${t.priority === "high" ? `<span class="chip red">${icon("flag", 11)} High</span>` : ""}</span></div>
      <div class="tr-due"><span class="chip ${which === "open" ? urgency(t.due_at, now) : "grey"}">${esc(dueLabel(t.due_at, now))}</span><span class="tiny muted">${esc(fromNow(t.due_at, now))}</span></div>
      ${which === "open" && t.kind === "deliverable" ? `<div class="tr-left"><label class="tiny muted">Left <input type="number" class="compact num" min="0" step="0.25" value="${t.remaining_minutes / 60}" data-left aria-label="Hours left"> h</label>
        <span class="meter" title="${fmtMinutes(p)} planned of ${fmtMinutes(t.remaining_minutes)} left"><span style="width:${pct}%"></span></span><span class="tiny muted">${fmtMinutes(p) || "0 h"} planned</span></div>` : `<div class="tr-left"></div>`}
      <div class="tr-actions">${which === "open" ? `<button class="btn small" data-finish>${icon("check", 14)} Done</button>` : `<button class="btn small ghost" data-reopen>${icon("undo", 14)} Reopen</button>`}</div>
    </div>`;
  }).join("")}</div></section>`;
  body.querySelectorAll("[data-task]").forEach((row) => {
    const id = row.dataset.task;
    row.querySelector("[data-left]")?.addEventListener("change", async (e) => {
      try { await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { remaining_minutes: Math.round(parseFloat(e.target.value || "0") * 60) }); toast("Saved. Your plan will offer an update."); ctx.refreshShell(); }
      catch (err) { showError(err); }
    });
    row.querySelector("[data-finish]")?.addEventListener("click", async () => {
      try {
        await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { status: "done" });
        toast("Marked done.", "info", { label: "Undo", onClick: async () => { await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { status: "open" }); ctx.refresh(); } });
        ctx.refresh();
      } catch (err) { showError(err); }
    });
    row.querySelector("[data-reopen]")?.addEventListener("click", async () => {
      try { await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { status: "open" }); toast("Reopened."); ctx.refresh(); } catch (err) { showError(err); }
    });
  });
}

// ---- manual task --------------------------------------------------------------------------------
export async function addTaskDialog(ctx) {
  const now = ctx.workspace?.now;
  await modal("Add a task", `
    <div class="form-grid">
      <label class="field full">What <input type="text" id="t-title" placeholder="e.g. Revise lecture 7"></label>
      <label class="field">Course <input type="text" id="t-course" placeholder="optional, e.g. MLX5204"></label>
      <label class="field">Kind <select id="t-kind"><option value="deliverable">Work to do</option><option value="event">Exam or meeting</option></select></label>
      <label class="field">Deadline (or start) <input type="datetime-local" id="t-due" value="${now ? toLocalInput(now).slice(0, 11) + "23:59" : ""}"></label>
      <label class="field">Effort (or length), hours <input type="number" id="t-effort" min="0" step="0.25" value="1"></label>
    </div>
    <label class="check"><input type="checkbox" id="t-prio"> High priority</label>`, {
    actions: [{ label: "Cancel", value: null }, {
      label: "Add task", primary: true, onClick: async (dlg) => {
        const title = dlg.querySelector("#t-title").value.trim();
        const due = fromLocalInput(dlg.querySelector("#t-due").value);
        if (!title || !due) { toast("Add what it is and when it's due.", "error"); return false; }
        await api.post("/api/tasks", {
          title, due_at: due, course_code: dlg.querySelector("#t-course").value.trim().toUpperCase() || null, kind: dlg.querySelector("#t-kind").value,
          remaining_minutes: Math.round(parseFloat(dlg.querySelector("#t-effort").value || "0") * 60), priority: dlg.querySelector("#t-prio").checked ? "high" : "medium",
        });
        toast("Task added. Your plan will offer an update.");
        ctx.refresh();
      },
    }],
  });
}
