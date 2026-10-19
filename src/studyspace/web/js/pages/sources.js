// 01 Sources: what the agent reads (email, timetable, course files) and what it found. Adding is secondary.
import { api } from "../api.js";
import { esc, fmtDate, fmtDateTime, fmtRange, hours, modal, sgDate, sgParts } from "../util.js";
import { ICON, addDialog, labelChips, openClass, openSource, senderLine, syncDialog } from "../sources-common.js";

export async function render(root, ctx) {
  const o = await api.get("/api/overview");
  const a = o.agent;
  const empty = !a.messages && !a.files && !a.classes;

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">What Studyspace reads</p>
        <h1>Everything your plan is built on.</h1>
        <p class="lede">Everything your agent reads. Open any item to see the original and what was found in it.</p>
      </div>
      <span class="step-tag">STEP 01 OF 03</span>
    </div>

    ${empty ? emptyAgent() : agentCard(a)}

    <div class="source-grid">
      ${emailCard(o.inbox)}
      ${timetableCard(o.timetable, o.now)}
      ${filesCard(o.files)}
    </div>

    <div class="grid" style="margin-top:22px">
      <section class="card">
        <div class="card-head"><h2>What Studyspace did</h2><button class="btn small ghost" id="all-activity">Full log</button></div>
        <div class="card-body">${timeline(o.activity)}</div>
      </section>
      <aside class="stack">
        <section class="card soft"><div class="card-body">
          <p class="side-title">You stay in control</p>
          <p class="small muted" style="margin:0 0 8px">Sources are read on this computer. A task enters your plan only after you check its deadline and effort, and nothing is ever sent for you.</p>
          <a class="btn small" href="#/privacy">See what would leave this computer</a>
        </div></section>
      </aside>
    </div>`;

  root.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => addDialog(b.dataset.add, ctx)));
  root.querySelectorAll("[data-sync]").forEach((b) => b.addEventListener("click", () => syncDialog(b.dataset.sync, ctx)));
  root.querySelectorAll("[data-source]").forEach((b) => b.addEventListener("click", () => openSource(b.dataset.source, ctx)));
  root.querySelectorAll("[data-class]").forEach((b) => b.addEventListener("click", () => openClass(JSON.parse(b.dataset.class))));
  root.querySelector("#all-activity").addEventListener("click", async () => {
    const all = await api.get("/api/activity");
    modal("Everything Studyspace did", timeline(all), { wide: true, actions: [{ label: "Close", value: true }] });
  });
}

function agentCard(a) {
  const stat = (n, label, href, tone = "") => `<a class="stat ${tone}" href="${href}"><b>${n}</b><span>${label}</span></a>`;
  const parts = [
    a.messages ? `${a.messages} message${a.messages === 1 ? "" : "s"}` : "",
    a.files ? `${a.files} course file${a.files === 1 ? "" : "s"}` : "",
    a.classes ? "your timetable" : "",
  ].filter(Boolean);
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  return `
  <section class="card agent-card">
    <div class="agent-intro">
      <span class="agent-icon">${ICON.spark}</span>
      <div><p class="side-title" style="margin:0 0 4px">What your agent found</p>
      <p class="agent-line">From ${esc(list)}, Studyspace found:</p></div>
    </div>
    <div class="stats">
      ${stat(a.to_review, `task${a.to_review === 1 ? "" : "s"} to check`, "#/tasks", a.to_review ? "accent" : "")}
      ${stat(a.replies, `repl${a.replies === 1 ? "y" : "ies"} waiting`, "#/replies", a.replies ? "amber" : "")}
      ${stat(a.due_7_days, `deadline${a.due_7_days === 1 ? "" : "s"} in 7 days`, "#/tasks")}
      ${stat(a.classes, "class sessions kept free", "#/plan")}
    </div>
    <a class="btn primary" href="${a.to_review ? "#/tasks" : "#/plan"}">${a.to_review ? "Check tasks" : a.plan_saved ? "Open your plan" : "Make a plan"} ${ICON.arrow}</a>
  </section>`;
}

function emptyAgent() {
  return `
  <section class="card agent-card">
    <div class="agent-intro">
      <span class="agent-icon">${ICON.spark}</span>
      <div><p class="side-title" style="margin:0 0 4px">Your agent is ready</p>
      <p class="agent-line">Add your emails, timetable and course files below, or try it with a fictional student first.</p></div>
    </div>
    <button class="btn primary" data-global="load-demo">Load demo student</button>
  </section>`;
}

function head(icon, title, sub, kind) {
  return `
  <div class="source-head">
    <span class="source-icon">${icon}</span>
    <div class="source-title"><h2>${title}</h2><p>${sub}</p></div>
    <div class="source-actions">
      <button class="icon-btn" data-add="${kind}" title="Add manually" aria-label="Add to ${title}">${ICON.plus}</button>
      <button class="btn tiny" data-sync="${kind}" title="Connect an app">${ICON.sync} Sync</button>
    </div>
  </div>`;
}

function updated(at) {
  return at ? `updated ${esc(fmtDateTime(at))}` : "nothing added yet";
}

function emailCard(inbox) {
  const sub = inbox.total ? `${inbox.total} messages · ${updated(inbox.updated_at)}` : "Course emails and messages";
  const rows = inbox.latest.map((i) => `
    <button class="source-row mail-row" data-source="${esc(i.record_id)}">
      <span class="row-main">
        <span class="row-line"><span class="row-title">${esc(i.subject || "(no subject)")}</span><span class="row-time">${esc(shortTime(i.received_at))}</span></span>
        <span class="row-line"><span class="row-sub">${senderLine(i)}</span><span class="labels">${labelChips(i.labels.filter((l) => l !== "info"))}</span></span>
      </span>
    </button>`).join("");
  return `
  <section class="card source-card">
    ${head(ICON.mail, "Email", sub, "email")}
    <div class="source-body">${rows || emptyRows("No messages yet.", "Add saved emails or paste a message with +.")}</div>
    <div class="source-foot">
      ${inbox.total ? `<a href="#/inbox">View all ${inbox.total} messages ${ICON.arrow}</a>` : "<span></span>"}
      ${inbox.needs_reply ? `<span class="chip amber">${inbox.needs_reply} waiting for you</span>` : ""}
    </div>
  </section>`;
}

function timetableCard(t, now) {
  const sub = t.classes_total ? `${t.weekly} classes a week · ${updated(t.updated_at)}` : "Classes, meetings and exams";
  const today = sgDate(now);
  const byDay = {};
  for (const c of t.this_week) (byDay[sgDate(c.start)] ||= []).push(c);
  const days = Object.keys(byDay).sort();
  const rows = days.map((d) => {
    const p = sgParts(d + "T12:00:00+08:00");
    return `<div class="tt-day ${d === today ? "today" : ""} ${d < today ? "past" : ""}">
      <span class="tt-label">${p.weekday}<small>${p.d}</small></span>
      <span class="tt-items">${byDay[d].map((c) => `<button class="tt-item ${c.origin === "manual" ? "own" : ""}" data-class='${esc(JSON.stringify(c))}'><span>${esc(fmtRange(c.start, c.end))}</span>${esc(c.label || "Busy")}</button>`).join("")}</span>
    </div>`;
  }).join("");
  const events = t.upcoming_events.map((e) => `<div class="tt-event"><b>${esc(e.title)}</b><span>${esc(fmtDateTime(e.start))}${e.confirmed ? "" : " · to check"}</span></div>`).join("");
  return `
  <section class="card source-card">
    ${head(ICON.calendar, "Timetable", sub, "timetable")}
    <div class="source-body">
      ${rows ? `<p class="mini-title">This week</p>${rows}` : emptyRows("No timetable yet.", "Add your NUSMods .ics file with +.")}
      ${events ? `<p class="mini-title" style="margin-top:12px">Exams and events coming up</p>${events}` : ""}
    </div>
    <div class="source-foot">
      <a href="#/plan?edit=hours">Free study hours this week: <b>${hours(t.free_minutes_week)} h</b> ${ICON.arrow}</a>
      ${t.commitments ? `<span class="chip grey">${t.commitments} added by you</span>` : ""}
    </div>
  </section>`;
}

function filesCard(f) {
  const sub = f.total ? `${f.total} file${f.total === 1 ? "" : "s"} · ${updated(f.updated_at)}` : "Slides, briefs and reading lists";
  const rows = f.items.map((x) => `
    <button class="source-row" data-source="${esc(x.record_id)}">
      <span class="file-badge">PDF</span>
      <span class="row-main">
        <span class="row-title">${esc(x.title || x.filename)}</span>
        <span class="row-sub">${esc(x.course_code || "")}${x.pages ? ` · ${x.pages} page${x.pages === 1 ? "" : "s"}` : ""}${x.no_text ? " · no readable text" : ""}</span>
      </span>
      <span class="row-side">${x.tasks ? `<span class="chip">${x.tasks} task${x.tasks === 1 ? "" : "s"} found</span>` : `<span class="chip outline">no deadlines</span>`}</span>
    </button>`).join("");
  return `
  <section class="card source-card">
    ${head(ICON.file, "Course files", sub, "files")}
    <div class="source-body">${rows || emptyRows("No course files yet.", "Add an assignment brief or lecture slides (PDF) with +.")}</div>
    <div class="source-foot"><span class="tiny muted">Deadlines in briefs are merged with the emails about the same task.</span></div>
  </section>`;
}

function emptyRows(title, hint) {
  return `<div class="source-empty"><strong>${esc(title)}</strong>${esc(hint)}</div>`;
}

function shortTime(iso) {
  if (!iso) return "";
  return fmtDate(iso);
}

const KIND_DOT = { email: "purple", paste: "purple", file: "blue", timetable: "grey", free_time: "green", extract: "accent", plan: "green", removed: "red" };

function timeline(items) {
  if (!items.length) return `<p class="small muted" style="margin:0">Nothing yet. Every time Studyspace reads something or finds a task, it is listed here.</p>`;
  return `<ol class="timeline">${items.map((x) => `
    <li><span class="t-dot ${KIND_DOT[x.kind] || "grey"}"></span>
      <span class="t-text">${esc(x.label)}</span>
      <span class="t-time">${esc(fmtDateTime(x.created_at))}</span></li>`).join("")}</ol>`;
}
