// 02 Review tasks (gate 1): nothing is planned until the student confirms the deadline and the effort.
import { api } from "../api.js";
import {
  FLAG_TEXT, busy, esc, flagChips, fmtDateTime, fmtDay, fromLocalInput, hours, modal, senderName, showError, toLocalInput, toast,
} from "../util.js";

let edits = {};      // candidate_id -> {title, due, effort, priority, selected}
let focusId = null;

export async function render(root, ctx, params) {
  const [cands, tasks, sources] = await Promise.all([api.get("/api/candidates"), api.get("/api/tasks"), api.get("/api/sources")]);
  const pending = cands.filter((c) => c.status === "pending");
  const srcById = Object.fromEntries(sources.map((s) => [s.record_id, s]));
  const taskById = Object.fromEntries(tasks.map((t) => [t.task_id, t]));
  focusId = params.get("focus") || (pending.some((c) => c.candidate_id === focusId) ? focusId : pending[0]?.candidate_id);

  for (const c of pending) {
    if (edits[c.candidate_id]) continue;
    edits[c.candidate_id] = {
      title: c.title,
      due: toLocalInput(c.due_at),
      effort: c.kind === "event" ? "1" : "",
      priority: "medium",
      selected: Boolean(c.due_at),
    };
  }

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">You have the final say</p>
        <h1>Good plans start with the right details.</h1>
        <p class="lede">Check the source, correct the date, and tell us how much work remains. Effort means work still to do.</p>
      </div>
      <span class="step-tag">STEP 02 OF 03</span>
    </div>
    <div class="grid wide-side">
      <div class="stack">
        <section class="card">
          <div class="card-head">
            <h2>${pending.length} task${pending.length === 1 ? "" : "s"} to review</h2>
            <button class="btn small" id="add-task">+ Add task</button>
          </div>
          ${pending.length ? pendingTable(pending, srcById) : `<div class="empty"><strong>All caught up</strong>New tasks appear here when messages are added.</div>`}
          ${pending.length ? `<div class="card-foot">Tasks without a deadline or an effort estimate stay here until you complete them. All values remain editable.</div>` : ""}
        </section>
        ${pending.length ? `<div class="row between"><a class="btn" href="#/inbox">← Inbox</a><button class="btn primary" id="confirm-btn">Confirm selected tasks →</button></div>` : ""}
        <section class="card">
          <div class="card-head"><h2>Confirmed tasks</h2><a class="btn small" href="#/plan">Plan these →</a></div>
          ${confirmedTable(tasks)}
        </section>
      </div>
      <aside class="stack" id="evidence">${evidence(pending.find((c) => c.candidate_id === focusId), srcById, taskById)}</aside>
    </div>`;

  bind(root, ctx, pending, srcById, taskById, tasks);
}

function pendingTable(pending, srcById) {
  return `<div class="table-wrap"><table>
    <thead><tr><th><input type="checkbox" class="check" id="select-all" aria-label="Select all"></th><th>Task</th><th>Deadline · SGT</th><th>Effort · h</th><th>Priority</th><th>Notes</th><th></th></tr></thead>
    <tbody>${pending.map((c) => row(c, srcById)).join("")}</tbody></table></div>`;
}

function row(c, srcById) {
  const e = edits[c.candidate_id];
  const missingDue = !e.due;
  const missingEffort = c.kind !== "event" && !e.effort;
  const src = srcById[c.source_ids[c.source_ids.length - 1]];
  const hint = !e.due
    ? c.due_options.length ? "choose a time →" : c.due_date ? `${fmtDay(c.due_date + "T12:00:00+08:00")} · add a time` : "no deadline in message"
    : "";
  return `<tr data-row="${esc(c.candidate_id)}" class="${focusId === c.candidate_id ? "selected-row" : ""} ${missingDue || missingEffort ? "needs" : ""}">
    <td><input type="checkbox" class="check" data-field="selected" ${e.selected ? "checked" : ""} aria-label="Select ${esc(c.title)}"></td>
    <td><input type="text" class="compact title-input" data-field="title" value="${esc(e.title)}" aria-label="Task title">
      <div class="tiny muted" style="margin-top:4px">${esc(c.course_code || "")}${c.kind === "event" ? " · event" : ""}${src ? ` · ${esc(senderName(src.sender))}` : ""}</div></td>
    <td><input type="datetime-local" class="compact ${missingDue ? "invalid" : ""}" data-field="due" value="${esc(e.due)}" aria-label="Deadline">
      ${hint ? `<div class="tiny" style="color:var(--amber);margin-top:4px">${esc(hint)}</div>` : ""}</td>
    <td><input type="number" class="compact ${missingEffort ? "invalid" : ""}" style="width:76px" min="0" step="0.25" data-field="effort" value="${esc(e.effort)}" placeholder="${c.kind === "event" ? "length" : "e.g. 2"}" aria-label="${c.kind === "event" ? "Length in hours" : "Effort in hours"}"></td>
    <td><select class="compact" data-field="priority" aria-label="Priority">${["high", "medium", "low"].map((p) => `<option value="${p}" ${e.priority === p ? "selected" : ""}>${p[0].toUpperCase() + p.slice(1)}</option>`).join("")}</select></td>
    <td>${flagChips(c.flags)}${c.related_task_id ? ` <span class="chip blue">Updates a task</span>` : ""}</td>
    <td><button class="btn tiny ghost" data-view="${esc(c.candidate_id)}">View</button></td>
  </tr>`;
}

function evidence(c, srcById, taskById) {
  if (!c) {
    return `<section class="card soft"><div class="card-body">
      <p class="side-title">Source evidence</p>
      <p class="small muted" style="margin:0">Select a task to see the sentence it came from, the message, and any earlier dates.</p>
    </div></section>`;
  }
  const sources = c.source_ids.map((id) => srcById[id]).filter(Boolean);
  const latest = sources[sources.length - 1];
  const related = c.related_task_id ? taskById[c.related_task_id] : null;
  const e = edits[c.candidate_id];
  const options = c.due_options || [];
  return `
  <section class="card"><div class="card-body">
    <p class="side-title">Source evidence</p>
    <h2 style="font-size:17px;margin:0 0 12px">${esc(c.title)}</h2>
    <div class="quote">${esc(c.evidence)}</div>
    ${c.due_text ? `<p class="small muted" style="margin:10px 0 0">Deadline as written: <b style="color:var(--ink)">“${esc(c.due_text)}”</b></p>` : ""}
    ${options.length ? `
      <div class="alert amber" style="margin-top:14px">
        <strong>${c.flags.includes("MIDNIGHT_AMBIGUITY") ? "Two possible deadlines" : "Suggested time"}</strong>
        <span>${c.flags.includes("MIDNIGHT_AMBIGUITY") ? "“Midnight” can mean the start or the end of the day. Pick the one the course means." : "The message ties this to another event. Confirm the time that works."}</span>
        <div class="segmented">${options.map((o) => `<button class="option-btn ${e.due === toLocalInput(o) ? "selected" : ""}" data-pick="${esc(toLocalInput(o))}">${esc(fmtDateTime(o))}${o.endsWith("T00:00:00+08:00") ? " · start of the day" : o.includes("T23:59") ? " · end of the day" : ""}</button>`).join("")}</div>
      </div>` : ""}
    ${!e.due && !options.length && c.due_date ? `
      <div class="alert amber" style="margin-top:14px">
        <strong>Day known, time missing</strong>
        <span>The message gives ${esc(fmtDay(c.due_date + "T12:00:00+08:00"))} but no time. Choose one:</span>
        <div class="row">
          <button class="btn small" data-pick="${c.due_date}T09:00">09:00</button>
          <button class="btn small" data-pick="${c.due_date}T12:00">12:00</button>
          <button class="btn small" data-pick="${c.due_date}T17:00">17:00</button>
          <button class="btn small" data-pick="${c.due_date}T23:59">23:59</button>
        </div>
      </div>` : ""}
    ${related ? `
      <div class="alert purple" style="margin-top:14px">
        <strong>Updates your task “${esc(related.title)}”</strong>
        <span>Current deadline: ${esc(fmtDateTime(related.due_at))}<br>New deadline: ${esc(c.due_at ? fmtDateTime(c.due_at) : c.due_text || "to check")}</span>
        <div class="row"><button class="btn small primary" data-apply="${esc(c.candidate_id)}">Use new date</button><button class="btn small" data-dismiss="${esc(c.candidate_id)}">Keep current date</button></div>
      </div>` : ""}
    ${c.history.length ? `
      <p class="side-title" style="margin-top:18px">Earlier versions</p>
      <ul class="history">${c.history.map((h) => `<li><s>${esc(h.due_at ? fmtDateTime(h.due_at) : h.due_date || "no date")}</s><span>from ${esc(srcById[h.source_id]?.subject || h.source_id)}</span></li>`).join("")}
      <li><b style="color:var(--ink)">${esc(c.due_at ? fmtDateTime(c.due_at) : c.due_date || "to confirm")}</b><span>latest</span></li></ul>` : ""}
    ${c.flags.length ? `<p class="side-title" style="margin-top:18px">Notes</p>${c.flags.map((f) => `<p class="small muted" style="margin:0 0 6px">${flagChips([f])} ${esc((FLAG_TEXT[f] || [, , f])[2])}</p>`).join("")}` : ""}
    <dl class="meta-list" style="margin-top:18px">
      <div><dt>Source${sources.length > 1 ? `s (${sources.length})` : ""}</dt><dd>${sources.map((s) => `<a href="#/inbox?open=${encodeURIComponent(s.record_id)}">${esc(s.subject || s.record_id)}</a>`).join("<br>")}</dd></div>
      <div><dt>Received</dt><dd>${esc(latest ? fmtDateTime(latest.received_at) : "—")}</dd></div>
      <div><dt>Status</dt><dd>Awaiting your confirmation</dd></div>
    </dl>
    <button class="btn small danger" data-dismiss="${esc(c.candidate_id)}">Not a task — dismiss</button>
  </div></section>`;
}

function confirmedTable(tasks) {
  if (!tasks.length) return `<div class="empty">Confirmed tasks appear here.</div>`;
  const sorted = [...tasks].sort((a, b) => (a.status === b.status ? a.due_at.localeCompare(b.due_at) : a.status === "open" ? -1 : 1));
  return `<div class="table-wrap"><table>
    <thead><tr><th>Task</th><th>Deadline</th><th>Left · h</th><th>Priority</th><th></th></tr></thead>
    <tbody>${sorted.map((t) => `<tr data-task="${esc(t.task_id)}" style="${t.status === "done" ? "opacity:.55" : ""}">
      <td><b>${esc(t.title)}</b><div class="tiny muted">${esc(t.course_code || "")}${t.kind === "event" ? " · event" : ""}</div></td>
      <td>${esc(fmtDateTime(t.due_at))}</td>
      <td>${t.kind === "event" ? `<span class="muted small">${hours(t.remaining_minutes)} h long</span>` : `<input type="number" class="compact" style="width:72px" min="0" step="0.25" value="${hours(t.remaining_minutes)}" data-remaining aria-label="Hours left">`}</td>
      <td><span class="chip ${t.priority === "high" ? "red" : t.priority === "low" ? "grey" : ""}">${t.priority}</span></td>
      <td style="text-align:right">${t.status === "open" ? `<button class="btn tiny" data-done>Mark done</button>` : `<button class="btn tiny ghost" data-reopen>Reopen</button>`}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

function bind(root, ctx, pending, srcById, taskById, tasks) {
  const table = root.querySelector("tbody");
  root.querySelectorAll("[data-row]").forEach((tr) => {
    const id = tr.dataset.row;
    tr.addEventListener("input", (e) => {
      const f = e.target.dataset.field;
      if (!f) return;
      edits[id][f] = f === "selected" ? e.target.checked : e.target.value;
      if (f === "due" || f === "effort") {
        e.target.classList.toggle("invalid", !e.target.value);
        if (e.target.value && !edits[id].selected && edits[id].due && (edits[id].effort || pending.find((c) => c.candidate_id === id).kind === "event")) {
          edits[id].selected = true;
          tr.querySelector('[data-field="selected"]').checked = true;
        }
      }
    });
    tr.addEventListener("click", (e) => {
      if (e.target.closest("input,select,button") && !e.target.closest("[data-view]")) return;
      focusId = id;
      root.querySelectorAll("[data-row]").forEach((r) => r.classList.toggle("selected-row", r.dataset.row === id));
      root.querySelector("#evidence").innerHTML = evidence(pending.find((c) => c.candidate_id === id), srcById, taskById);
    });
  });
  root.querySelector("#select-all")?.addEventListener("change", (e) => {
    pending.forEach((c) => (edits[c.candidate_id].selected = e.target.checked));
    root.querySelectorAll('[data-field="selected"]').forEach((cb) => (cb.checked = e.target.checked));
  });

  root.querySelector("#evidence").addEventListener("click", async (e) => {
    const pick = e.target.closest("[data-pick]");
    if (pick && focusId) {
      const ed = edits[focusId];
      ed.due = pick.dataset.pick;
      const tr = table?.querySelector(`[data-row="${CSS.escape(focusId)}"]`);
      const input = tr?.querySelector('[data-field="due"]');
      if (input) {
        input.value = pick.dataset.pick;
        input.classList.remove("invalid");
        input.nextElementSibling?.remove();  // the "choose a time" hint
      }
      const cand = pending.find((c) => c.candidate_id === focusId);
      if (tr && (ed.effort || cand.kind === "event")) {
        ed.selected = true;
        tr.querySelector('[data-field="selected"]').checked = true;
      }
      root.querySelector("#evidence").innerHTML = evidence(pending.find((c) => c.candidate_id === focusId), srcById, taskById);
      return;
    }
    const dismiss = e.target.closest("[data-dismiss]");
    if (dismiss) {
      try {
        await api.post(`/api/candidates/${encodeURIComponent(dismiss.dataset.dismiss)}/dismiss`);
        delete edits[dismiss.dataset.dismiss];
        toast("Dismissed. It will not come back when messages are re-read.");
        ctx.refresh();
      } catch (err) { showError(err); }
      return;
    }
    const apply = e.target.closest("[data-apply]");
    if (apply) {
      const c = pending.find((x) => x.candidate_id === apply.dataset.apply);
      await confirmOne(c, ctx, true);
    }
  });

  root.querySelector("#confirm-btn")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const chosen = pending.filter((c) => edits[c.candidate_id].selected);
    if (!chosen.length) return toast("Select at least one task.", "error");
    let ok = 0;
    const stuck = [];
    for (const c of chosen) {
      const e2 = edits[c.candidate_id];
      if (!e2.due || (c.kind !== "event" && !e2.effort)) { stuck.push(c.title); continue; }
      try { await confirmOne(c, ctx, false); ok++; } catch (err) { stuck.push(`${c.title} (${err.message})`); }
    }
    toast(`${ok} task(s) confirmed.${stuck.length ? ` ${stuck.length} still need a deadline or effort.` : ""}`, stuck.length && !ok ? "error" : "info");
    ctx.refresh();
  }));

  root.querySelector("#add-task").addEventListener("click", () => addTaskDialog(ctx));

  root.querySelectorAll("[data-task]").forEach((tr) => {
    const id = tr.dataset.task;
    tr.querySelector("[data-remaining]")?.addEventListener("change", async (e) => {
      try {
        await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { remaining_minutes: Math.round(parseFloat(e.target.value || "0") * 60) });
        toast("Saved. Re-plan to use the new estimate.");
        ctx.refreshShell();
      } catch (err) { showError(err); }
    });
    tr.querySelector("[data-done]")?.addEventListener("click", async () => {
      try { await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { status: "done" }); toast("Marked done."); ctx.refresh(); } catch (err) { showError(err); }
    });
    tr.querySelector("[data-reopen]")?.addEventListener("click", async () => {
      try { await api.patch(`/api/tasks/${encodeURIComponent(id)}`, { status: "open" }); ctx.refresh(); } catch (err) { showError(err); }
    });
  });
}

async function confirmOne(c, ctx, refresh) {
  const e = edits[c.candidate_id];
  const body = { title: e.title, priority: e.priority, due_at: fromLocalInput(e.due) };
  if (e.effort !== "") body.remaining_minutes = Math.round(parseFloat(e.effort) * 60);
  if (!body.due_at) delete body.due_at;
  await api.post(`/api/candidates/${encodeURIComponent(c.candidate_id)}/confirm`, body);
  delete edits[c.candidate_id];
  if (refresh) { toast("Task updated."); ctx.refresh(); }
}

async function addTaskDialog(ctx) {
  const now = ctx.workspace?.now;
  await modal("Add a task", `
    <div class="form-grid">
      <label class="field full">Title <input type="text" id="t-title" placeholder="e.g. Revise lecture 7"></label>
      <label class="field">Course <input type="text" id="t-course" placeholder="optional"></label>
      <label class="field">Kind <select id="t-kind"><option value="deliverable">Work to do</option><option value="event">Event (exam, meeting)</option></select></label>
      <label class="field">Deadline or start · SGT <input type="datetime-local" id="t-due" value="${now ? toLocalInput(now).slice(0, 11) + "23:59" : ""}"></label>
      <label class="field">Effort or length · h <input type="number" id="t-effort" min="0" step="0.25" value="1"></label>
      <label class="field">Priority <select id="t-priority"><option>medium</option><option>high</option><option>low</option></select></label>
    </div>`, {
    actions: [{ label: "Cancel", value: null }, {
      label: "Add task", primary: true, onClick: async (dlg) => {
        const title = dlg.querySelector("#t-title").value.trim();
        const due = fromLocalInput(dlg.querySelector("#t-due").value);
        if (!title || !due) { toast("Add a title and a deadline.", "error"); return false; }
        await api.post("/api/tasks", {
          title, due_at: due, course_code: dlg.querySelector("#t-course").value || null, kind: dlg.querySelector("#t-kind").value,
          remaining_minutes: Math.round(parseFloat(dlg.querySelector("#t-effort").value || "0") * 60), priority: dlg.querySelector("#t-priority").value,
        });
        toast("Task added.");
        ctx.refresh();
      },
    }],
  });
}

