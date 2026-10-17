// 05 Find a meeting time: free slots around classes, exams, meetings and locked study sessions.
import { api } from "../api.js";
import { addDays, busy, esc, fmtDateTime, fmtRange, sgDate, showError, toast } from "../util.js";

let last = null;

export async function render(root, ctx) {
  const today = sgDate(ctx.workspace.now);
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Group work, less back-and-forth</p>
        <h1>Find a time that works.</h1>
        <p class="lede">Studyspace checks your classes, exams, meetings and locked study sessions. Add your groupmates' calendars to check theirs too.</p>
      </div>
    </div>
    <div class="grid wide-side">
      <section class="card">
        <div class="card-head"><h2>Meeting details</h2></div>
        <div class="card-body stack">
          <div class="form-grid">
            <label class="field">Title <input type="text" id="m-title" value="Project meeting"></label>
            <label class="field">Length <select id="m-len"><option value="30">30 min</option><option value="60" selected>1 hour</option><option value="90">1.5 hours</option><option value="120">2 hours</option></select></label>
            <label class="field">From <input type="date" id="m-from" value="${today}"></label>
            <label class="field">To <input type="date" id="m-to" value="${addDays(today, 6)}"></label>
            <label class="field">Earliest <input type="time" id="m-ws" value="09:00"></label>
            <label class="field">Latest end <input type="time" id="m-we" value="21:00"></label>
            <label class="check full"><input type="checkbox" id="m-wd"> Weekdays only</label>
            <label class="field full">Groupmates' calendars (optional)
              <textarea id="m-ics" placeholder="Paste the contents of their .ics export here, or choose files below. Only the busy times are used; titles are ignored and nothing is stored." style="min-height:90px"></textarea>
              <input type="file" id="m-files" accept=".ics" multiple>
            </label>
          </div>
          <div class="row between"><span class="tiny muted">Planned (unlocked) study sessions are avoided when possible.</span><button class="btn primary" id="m-find">Find times</button></div>
        </div>
      </section>
      <aside class="stack" id="m-results">${last ? results(last) : `<section class="card soft"><div class="card-body small muted">Results appear here. Pick one to add it to your calendar; then re-plan if it moves a study session.</div></section>`}</aside>
    </div>`;

  root.querySelector("#m-files").addEventListener("change", async (e) => {
    const texts = await Promise.all([...e.target.files].map((f) => f.text()));
    const area = root.querySelector("#m-ics");
    area.value = [area.value, ...texts].filter(Boolean).join("\n");
    toast(`${e.target.files.length} calendar file(s) added.`);
  });
  root.querySelector("#m-find").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      const r = await api.post("/api/meetings/suggest", {
        duration_minutes: +root.querySelector("#m-len").value,
        start_date: root.querySelector("#m-from").value, end_date: root.querySelector("#m-to").value,
        window_start: root.querySelector("#m-ws").value, window_end: root.querySelector("#m-we").value,
        weekdays_only: root.querySelector("#m-wd").checked, others_busy_ics: root.querySelector("#m-ics").value || null,
      });
      last = { ...r, title: root.querySelector("#m-title").value || "Meeting" };
      root.querySelector("#m-results").innerHTML = results(last);
      bindResults(root, ctx);
    } catch (err) { showError(err); }
  }));
  bindResults(root, ctx);
}

function results(r) {
  if (!r.slots.length) return `<section class="card"><div class="empty"><strong>No common time found</strong>Try a longer date range, a shorter meeting, or later hours.</div></section>`;
  const text = r.slots.map((s) => `- ${fmtDateTime(s.start)}–${fmtRange(s.start, s.end).split("–")[1].trim()}`).join("\n");
  return `<section class="card">
    <div class="card-head"><h2>${r.slots.length} option${r.slots.length === 1 ? "" : "s"}</h2><button class="btn small" data-copy="${esc(text)}">Copy all</button></div>
    <div class="card-body stack" style="gap:10px">
      ${r.slots.map((s) => `<div class="row between" style="border:1px solid var(--line);border-radius:10px;padding:10px 12px">
        <span><b>${esc(fmtDateTime(s.start))}</b> <span class="muted">– ${esc(fmtRange(s.start, s.end).split("–")[1])}</span>${s.note ? `<div class="tiny" style="color:var(--amber)">${esc(s.note)}</div>` : ""}</span>
        <button class="btn tiny primary" data-add='${esc(JSON.stringify(s))}'>Add to my calendar</button></div>`).join("")}
      <p class="tiny muted" style="margin:0">Checked against ${r.considered_busy} busy period(s).</p>
    </div></section>`;
}

function bindResults(root, ctx) {
  root.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", async () => {
    const s = JSON.parse(b.dataset.add);
    try {
      await api.post("/api/calendar/busy", { start: s.start, end: s.end, label: last?.title || "Meeting" });
      b.outerHTML = `<span class="chip green">Added</span>`;
      toast("Added to your calendar. If it moves a study session, the plan page will ask you to re-plan.");
      ctx.refreshShell();
    } catch (err) { showError(err); }
  }));
  root.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); toast("Copied the options."); } catch { toast("Copy not available in this browser.", "error"); }
  }));
}
