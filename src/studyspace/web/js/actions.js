// Actions shared by Today, Tasks and Study plan, so the same click does the same thing everywhere.
import { api } from "./api.js";
import { courseTag, dueLabel, esc, fmtDateTime, fmtMinutes, fmtRange, fmtTime, fromLocalInput, fromNow, hours, minutesBetween, modal, showError, toast } from "./util.js";

export const EFFORT_CHOICES = [15, 30, 60, 90, 120, 180, 300, 480];

/** Gate 1 in one call, with Undo. */
export async function confirmCandidate(ctx, candidate, { due_at = null, minutes = null, priority = "medium", title = null } = {}, refresh = true) {
  const body = { priority };
  if (due_at) body.due_at = due_at;
  if (minutes != null) body.remaining_minutes = minutes;
  if (title && title !== candidate.title) body.title = title;
  const r = await api.post(`/api/candidates/${encodeURIComponent(candidate.candidate_id)}/confirm`, body);
  toast(r.updated_existing ? `Updated “${r.task.title}”.` : `Confirmed “${r.task.title}”.`, "info", {
    label: "Undo",
    onClick: async () => { await api.post(`/api/candidates/${encodeURIComponent(candidate.candidate_id)}/restore`); toast("Back in your list."); ctx.refresh(); },
  });
  if (refresh) ctx.refresh();
  return r;
}

export async function dismissCandidate(ctx, candidate, refresh = true) {
  await api.post(`/api/candidates/${encodeURIComponent(candidate.candidate_id)}/dismiss`);
  toast(`“${candidate.title}” set aside.`, "info", {
    label: "Undo",
    onClick: async () => { await api.post(`/api/candidates/${encodeURIComponent(candidate.candidate_id)}/restore`); toast("Back in your list."); ctx.refresh(); },
  });
  if (refresh) ctx.refresh();
}

/** Record a finished session; asks how much is left so the next plan uses a real number. */
export async function recordDone(ctx, block, task) {
  const mins = minutesBetween(block.start, block.end);
  const left = Math.max(0, (task?.remaining_minutes ?? mins) - mins);
  return modal("Session done", `
    <p style="margin:0"><b>${esc(task?.title || block.title || "Session")}</b><br>
    <span class="muted small">${esc(fmtDateTime(block.start))} – ${esc(fmtTime(block.end))} · ${esc(fmtMinutes(mins))}</span></p>
    <label class="field">Work left on this task (hours)
      <input type="number" id="left" min="0" step="0.25" value="${hours(left)}">
      <span class="hint">Faster or slower than planned? Change it. 0 means the task is finished.</span>
    </label>`, {
    actions: [{ label: "Cancel", value: null }, {
      label: "Record", primary: true, onClick: async (dlg) => {
        const leftMin = Math.round(parseFloat(dlg.querySelector("#left").value || "0") * 60);
        const r = await api.post("/api/progress", {
          op_id: `${block.plan_id || "plan"}:${block.task_id}:${block.start}`, task_id: block.task_id,
          start: block.start, end: block.end, remaining_minutes: leftMin,
        });
        toast(!r.recorded ? "Already recorded." : r.task.status === "done" ? "Nice work. Task finished." : `Recorded. ${fmtMinutes(r.task.remaining_minutes)} left.`);
        ctx.refresh();
      },
    }],
  });
}

/** "I can't make this session": keep the time free from now on and propose a new plan. */
export async function cantMakeIt(ctx, block) {
  const ok = await modal("Can't make this session?", `
    <p style="margin:0">Studyspace will treat <b>${esc(fmtDateTime(block.start))} – ${esc(fmtTime(block.end))}</b> as busy and suggest a new plan.
    Nothing changes until you adopt it.</p>`, { actions: [{ label: "Keep it", value: false }, { label: "Find another time", primary: true, value: true }] });
  if (!ok) return;
  try {
    await api.post("/api/calendar/busy", { start: block.start, end: block.end, label: "Not available" });
    ctx.go("plan", "replan=1");
  } catch (err) { showError(err); }
}

export function sessionLabel(block) {
  return `${fmtRange(block.start, block.end)}`;
}

/** One small dialog to confirm a found task from anywhere (calendar, Today): time if needed, effort, done. */
export function quickConfirm(ctx, c) {
  const now = ctx.workspace.now;
  const needsTime = !c.due_at || c.flags.includes("MIDNIGHT_AMBIGUITY");
  const opts = c.due_options?.length
    ? c.due_options.map((o) => [o, `${dueLabel(o, now)}${o.endsWith("T00:00:00+08:00") ? " · start of day" : o.includes("T23:59") ? " · end of day" : ""}`])
    : c.due_date ? ["09:00", "12:00", "17:00", "23:59"].map((h) => [`${c.due_date}T${h}:00+08:00`, h]) : [];
  const choices = c.kind === "event" ? [60, 90, 120, 180] : [...new Set([...EFFORT_CHOICES, c.suggested_minutes].filter(Boolean))].sort((a, b) => a - b);
  let due = needsTime ? null : c.due_at;
  let minutes = c.suggested_minutes || (c.kind === "event" ? 60 : null);
  const why = c.flags.includes("MIDNIGHT_AMBIGUITY") ? "“Midnight”: the start or the end of the day?"
    : !c.due_at && c.due_date ? `The message gives ${c.due_text ? `“${c.due_text}”` : "the day"} but no time.`
    : !c.due_at ? "The message gives no deadline." : "";
  const p = modal(c.title, `
    <div class="qc">
      <p class="qc-meta">${courseTag(c.course_code)}${c.kind === "event" ? `<span class="chip blue">Event</span>` : ""}
        ${due ? `<span class="chip">${esc(dueLabel(due, now))} · ${esc(fromNow(due, now))}</span>` : ""}</p>
      <div class="quote small">${esc(c.evidence)}</div>
      ${needsTime ? `<div class="qc-row"><span class="tc-label">When</span><div class="stack" style="gap:6px">
        ${why ? `<span class="small muted">${esc(why)}</span>` : ""}
        <div class="seg" data-q-due>${opts.map(([v, l]) => `<button class="seg-btn" data-v="${esc(v)}">${esc(l)}</button>`).join("")}
        <input type="datetime-local" class="compact seg-input" data-q-input aria-label="Other date and time"></div></div></div>` : ""}
      <div class="qc-row"><span class="tc-label">${c.kind === "event" ? "Length" : "Effort"}</span><div class="seg small" data-q-min>
        ${choices.map((m) => `<button class="seg-btn ${m === minutes ? "on" : ""} ${m === c.suggested_minutes ? "suggested" : ""}" data-m="${m}">${esc(fmtMinutes(m).replace(" min", "m").replace(" h", "h"))}</button>`).join("")}</div></div>
      ${c.suggested_minutes && c.kind !== "event" ? `<p class="tiny muted" style="margin:0"><span class="sugg-dot"></span>suggested from the kind of work · change it if you know better</p>` : ""}
    </div>`, {
    actions: [
      { label: "Not a task", onClick: async () => { await dismissCandidate(ctx, c); } },
      { label: "Confirm", primary: true, onClick: async () => {
        if (!due) { toast("Pick when it is due.", "error"); return false; }
        if (!minutes) { toast("Pick how long it takes.", "error"); return false; }
        await confirmCandidate(ctx, c, { due_at: due, minutes });
      } },
    ],
  });
  const dlg = document.getElementById("modal");
  dlg.querySelector("[data-q-due]")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-v]");
    if (!b) return;
    due = b.dataset.v;
    dlg.querySelectorAll("[data-v]").forEach((x) => x.classList.toggle("on", x === b));
    dlg.querySelector("[data-q-input]").value = "";
  });
  dlg.querySelector("[data-q-input]")?.addEventListener("change", (e) => {
    due = fromLocalInput(e.target.value);
    dlg.querySelectorAll("[data-v]").forEach((x) => x.classList.remove("on"));
  });
  dlg.querySelector("[data-q-min]").addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]");
    if (!b) return;
    minutes = +b.dataset.m;
    dlg.querySelectorAll("[data-m]").forEach((x) => x.classList.toggle("on", x === b));
  });
  return p;
}
