// 01 Inbox: bring messages in, see what each one asks of you.
import { api } from "../api.js";
import { LABEL_TEXT, busy, esc, fmtDateTime, fromLocalInput, senderName, showError, toLocalInput, toast } from "../util.js";

const FILTERS = [["all", "All"], ["task", "Tasks"], ["reply", "Replies"], ["event", "Events"], ["info", "Info"], ["newsletter", "Newsletters"]];
let state = { filter: "all", selected: null, tab: "upload" };

export async function render(root, ctx, params) {
  const items = await api.get("/api/inbox");
  if (params.get("open")) state.selected = params.get("open");
  const ws = ctx.workspace;

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">A clear start</p>
        <h1>A little less admin. A little more focus.</h1>
        <p class="lede">Bring your course messages together. Studyspace finds the tasks and deadlines; you stay in charge.</p>
      </div>
      <span class="step-tag">STEP 01 OF 03</span>
    </div>
    <div class="grid wide-side">
      <div class="stack">
        ${addCard()}
        ${items.length ? listCard(items) : emptyCard()}
      </div>
      <aside class="stack" id="inbox-side">${items.length ? sidePanel(items, ws) : startingPoint()}</aside>
    </div>`;

  bindAdd(root, ctx);
  bindList(root, ctx, items);
  if (state.selected && items.some((i) => i.record_id === state.selected)) openMessage(root, ctx, items, state.selected);
}

function addCard() {
  return `
  <section class="card">
    <div class="card-head">
      <h2>Add messages</h2>
      <div class="tabs" role="tablist">
        <button role="tab" data-tab="upload" class="${state.tab === "upload" ? "active" : ""}">Upload files</button>
        <button role="tab" data-tab="paste" class="${state.tab === "paste" ? "active" : ""}">Paste text</button>
      </div>
    </div>
    <div class="card-body" data-pane="upload" ${state.tab === "upload" ? "" : "hidden"}>
      <label class="dropzone" id="dropzone">
        <input type="file" id="file-input" multiple accept=".eml,.csv,.ics,.json,.txt" class="sr-only">
        <strong>Drop files here or choose them</strong>
        Saved emails (.eml) from Outlook or Gmail · a CSV export · your timetable (.ics from NUSMods) · free time (.json)
      </label>
      <p class="tiny muted" style="margin:10px 0 0">Files are read on this computer. Importing the same email twice does not create a duplicate.</p>
    </div>
    <div class="card-body" data-pane="paste" ${state.tab === "paste" ? "" : "hidden"}>
      <div class="form-grid">
        <label class="field">Subject or source <input type="text" id="paste-subject" placeholder="e.g. Teams message from groupmate"></label>
        <label class="field">Received at · SGT <input type="datetime-local" id="paste-time"></label>
        <label class="field full">Message text <textarea id="paste-text" placeholder="Paste an announcement, a forwarded email or a chat message"></textarea></label>
      </div>
      <div class="row between" style="margin-top:12px">
        <span class="tiny muted">Relative dates such as "this Friday" are read from the received time.</span>
        <button class="btn primary" id="paste-btn">Add and find tasks →</button>
      </div>
    </div>
  </section>`;
}

function emptyCard() {
  return `
  <section class="card">
    <div class="empty">
      <strong>No messages yet</strong>
      Add your own messages above, or try Studyspace with a fictional student's inbox.
      <div class="row" style="justify-content:center;margin-top:16px">
        <button class="btn primary" data-global="load-demo">Load demo student</button>
      </div>
    </div>
  </section>`;
}

function listCard(items) {
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, k === "all" ? items.length : items.filter((i) => i.labels.includes(k)).length]));
  const shown = state.filter === "all" ? items : items.filter((i) => i.labels.includes(state.filter));
  return `
  <section class="card">
    <div class="card-head">
      <h2>${items.length} message${items.length === 1 ? "" : "s"}</h2>
      <div class="filters" role="group" aria-label="Filter messages">
        ${FILTERS.map(([k, label]) => `<button data-filter="${k}" class="${state.filter === k ? "active" : ""}">${label}<span class="n">${counts[k]}</span></button>`).join("")}
      </div>
    </div>
    <div class="list" id="msg-list">
      ${shown.map(msgRow).join("") || `<div class="empty">Nothing in this view.</div>`}
    </div>
  </section>`;
}

function msgRow(i) {
  const labels = i.labels.map((l) => {
    const [text, color] = LABEL_TEXT[l] || [l, "grey"];
    return `<span class="chip ${color}">${text}</span>`;
  }).join("");
  return `
    <button class="msg ${state.selected === i.record_id ? "active" : ""}" data-open="${esc(i.record_id)}">
      <span>${i.urgent ? `<span class="urgent" title="Something is due within two days"></span>` : ""}</span>
      <span style="min-width:0">
        <span class="subject">${esc(i.subject || "(no subject)")}</span>
        <span class="meta">${esc(senderName(i.sender))}${i.course_code ? ` · ${esc(i.course_code)}` : ""}</span>
        <span class="snippet">${esc(i.snippet)}</span>
        <span class="labels">${labels}${i.draft_status === "reviewed" ? `<span class="chip green">Reply ready</span>` : ""}</span>
      </span>
      <span class="when">${esc(fmtDateTime(i.received_at))}</span>
    </button>`;
}

function startingPoint() {
  return `
  <section class="card"><div class="card-body">
    <p class="side-title">A simple starting point</p>
    <ol class="steps">
      <li><span><b>Bring in your messages</b>Upload saved emails, a CSV, your timetable, or paste text.</span></li>
      <li><span><b>Check the details</b>Every task shows the sentence it came from. Fix dates before they count.</span></li>
      <li><span><b>Make a workable plan</b>Only the hours you choose, never past a deadline.</span></li>
    </ol>
  </div></section>
  <section class="card soft"><div class="card-body">
    <p class="side-title">You stay in control</p>
    <p class="small muted" style="margin:0">A task enters your plan only after you confirm its deadline and effort. Nothing is sent on your behalf.</p>
  </div></section>`;
}

function sidePanel(items, ws) {
  const tasks = items.filter((i) => i.labels.includes("task")).length;
  const replies = items.filter((i) => i.labels.includes("reply")).length;
  const urgent = items.filter((i) => i.urgent).length;
  return `
  <section class="card glance"><div class="card-body">
    <p class="side-title">Your inbox at a glance</p>
    <div class="big-number">${ws.candidates_pending}<small>to review</small></div>
    <p class="small" style="color:var(--green);margin:6px 0 14px">tasks waiting for your check</p>
    <div class="kv"><span>Messages with tasks</span><b>${tasks}</b></div>
    <div class="kv"><span>Waiting for your reply</span><b>${replies}</b></div>
    <div class="kv"><span>Due within two days</span><b>${urgent}</b></div>
    <div style="margin-top:14px"><a class="btn primary" href="#/review">Review tasks →</a></div>
  </div></section>
  <section class="card soft"><div class="card-body small muted">Select a message to see its full text, the tasks found in it, and why it was labelled.</div></section>`;
}

function bindAdd(root, ctx) {
  root.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    state.tab = b.dataset.tab;
    root.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("active", x === b));
    root.querySelectorAll("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== state.tab));
  }));
  const pasteTime = root.querySelector("#paste-time");
  if (pasteTime && ctx.workspace) pasteTime.value = toLocalInput(ctx.workspace.now);

  const input = root.querySelector("#file-input");
  const zone = root.querySelector("#dropzone");
  const upload = async (files) => {
    if (!files.length) return;
    const form = new FormData();
    [...files].forEach((f) => form.append("files", f));
    zone.classList.add("over");
    try {
      const r = await api.upload("/api/import", form);
      await api.post("/api/extract");
      const added = r.files.reduce((n, f) => n + (f.added || 0) + (f.updated || 0), 0);
      const dup = r.files.reduce((n, f) => n + (f.duplicate || 0), 0);
      const slots = r.files.reduce((n, f) => n + (f.slots || 0), 0);
      const errors = r.files.filter((f) => f.error || (f.skipped && f.skipped.length));
      toast(`${added} new message(s)${dup ? `, ${dup} already here` : ""}${slots ? `, ${slots} calendar entries` : ""}.${errors.length ? " Some rows were skipped." : ""}`);
      ctx.refresh();
    } catch (err) { showError(err); } finally { zone.classList.remove("over"); }
  };
  input?.addEventListener("change", () => upload(input.files));
  zone?.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone?.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone?.addEventListener("drop", (e) => { e.preventDefault(); upload(e.dataTransfer.files); });

  root.querySelector("#paste-btn")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const text = root.querySelector("#paste-text").value.trim();
    if (!text) return toast("Paste some text first.", "error");
    try {
      const r = await api.post("/api/import/text", {
        text, subject: root.querySelector("#paste-subject").value || null,
        received_at: fromLocalInput(root.querySelector("#paste-time").value),
      });
      const ex = await api.post("/api/extract");
      const found = ex.candidates.filter((c) => c.status === "pending" && r.record_ids.some((id) => c.source_ids.includes(id))).length;
      toast(r.duplicate ? "This text was already added." : `Added. ${found} task(s) found.`);
      state.selected = r.record_ids[0];
      ctx.refresh();
    } catch (err) { showError(err); }
  }));
}

function bindList(root, ctx, items) {
  root.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => { state.filter = b.dataset.filter; ctx.refresh(); }));
  root.querySelector("#msg-list")?.addEventListener("click", (e) => {
    const row = e.target.closest("[data-open]");
    if (row) openMessage(root, ctx, items, row.dataset.open);
  });
}

async function openMessage(root, ctx, items, recordId) {
  state.selected = recordId;
  root.querySelectorAll(".msg").forEach((m) => m.classList.toggle("active", m.dataset.open === recordId));
  const side = root.querySelector("#inbox-side");
  const item = items.find((i) => i.record_id === recordId);
  side.innerHTML = `<section class="card"><div class="loading"><span class="spinner"></span></div></section>`;
  try {
    const [src, cands] = await Promise.all([api.get(`/api/sources/${encodeURIComponent(recordId)}`), api.get("/api/candidates")]);
    const mine = cands.filter((c) => c.source_ids.includes(recordId));
    side.innerHTML = `
    <section class="card"><div class="card-body">
      <p class="side-title">Message</p>
      <h2 style="font-size:16px;margin:0 0 10px">${esc(src.subject || "(no subject)")}</h2>
      <dl class="meta-list">
        <div><dt>From</dt><dd>${esc(src.sender || "—")}</dd></div>
        <div><dt>Received</dt><dd>${esc(fmtDateTime(src.received_at) || "—")}</dd></div>
        <div><dt>Why this label</dt><dd>${esc(item.reasons.join("; ") || "nothing to do")}</dd></div>
      </dl>
      <div class="message-body">${esc(src.body_text)}</div>
      ${mine.length ? `
        <p class="side-title" style="margin-top:18px">Tasks found</p>
        ${mine.map((c) => `<div class="task-line"><div class="row between"><b>${esc(c.title)}</b><span class="chip ${c.status === "confirmed" ? "green" : c.status === "dismissed" ? "grey" : ""}">${c.status}</span></div>
          <span class="muted">${c.due_at ? esc(fmtDateTime(c.due_at)) : c.due_date ? esc(c.due_date) + " · time to check" : "no deadline given"}</span></div>`).join("")}
        <a class="btn small" style="margin-top:10px" href="#/review?focus=${encodeURIComponent(mine[0].candidate_id)}">Review these tasks →</a>` : ""}
      <div class="row" style="margin-top:16px">
        ${item.labels.includes("reply") ? `<a class="btn primary small" href="#/replies?open=${encodeURIComponent(recordId)}">Draft a reply</a>` : ""}
        <a class="btn small" href="#/privacy?open=${encodeURIComponent(recordId)}">What a model would see</a>
      </div>
    </div></section>`;
  } catch (err) { showError(err); }
}
