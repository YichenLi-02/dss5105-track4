// Actions shared by Today, Tasks and Study plan, so the same click does the same thing everywhere.
import { api } from "./api.js";
import { esc, fmtDateTime, fmtMinutes, fmtRange, fmtTime, hours, minutesBetween, modal, showError, toast } from "./util.js";

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
