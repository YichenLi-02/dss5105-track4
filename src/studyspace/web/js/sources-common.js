// Shared pieces for the Sources and All messages pages: icons, the original viewer, add and sync dialogs.
import { api } from "./api.js";
import { LABEL_TEXT, confirmDialog, esc, fmtDateTime, fmtRange, fromLocalInput, modal, senderName, sgDate, showError, toLocalInput, toast } from "./util.js";

const svg = (path, size = 18) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
export const ICON = {
  mail: svg('<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m3.5 6.5 8.5 6.5 8.5-6.5"/>'),
  calendar: svg('<rect x="3" y="4.5" width="18" height="16" rx="2.5"/><path d="M3 9.5h18M8 3v3M16 3v3"/>'),
  file: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 16),
  sync: svg('<path d="M20 11a8 8 0 0 0-14.3-4.6L4 8"/><path d="M4 4v4h4M4 13a8 8 0 0 0 14.3 4.6L20 16"/><path d="M20 20v-4h-4"/>', 15),
  spark: svg('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>', 16),
  arrow: svg('<path d="M5 12h14M13 6l6 6-6 6"/>', 14),
};

export function labelChips(labels = []) {
  return labels.map((l) => {
    const [text, color] = LABEL_TEXT[l] || [l, "grey"];
    return `<span class="chip ${color}">${text}</span>`;
  }).join(" ");
}

// ---- viewer for originals -------------------------------------------------------------------
function highlightEvidence(body, evidences) {
  let html = esc(body);
  for (const ev of evidences) {
    const words = esc(ev).trim().split(/\s+/).filter(Boolean);
    if (words.length < 2) continue;
    const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
    try { html = html.replace(new RegExp(pattern), (m) => `<mark class="evidence">${m}</mark>`); } catch { /* ignore */ }
  }
  return html;
}

function foundList(cands) {
  if (!cands.length) return `<p class="small muted" style="margin:0">Nothing to do was found here.</p>`;
  return cands.map((c) => `<div class="task-line">
    <div class="row between"><b>${esc(c.title)}</b><span class="chip ${c.status === "confirmed" ? "green" : c.status === "dismissed" ? "grey" : ""}">${c.status === "pending" ? "to check" : c.status}</span></div>
    <span class="small muted">${c.due_at ? esc(fmtDateTime(c.due_at)) : c.due_date ? `${esc(c.due_date)} · time to choose` : c.due_text ? `“${esc(c.due_text)}” · day to choose` : "no deadline given"}${c.kind === "event" ? " · event" : ""}</span>
  </div>`).join("");
}

export async function openSource(recordId, ctx) {
  const [src, cands, inbox] = await Promise.all([
    api.get(`/api/sources/${encodeURIComponent(recordId)}`), api.get("/api/candidates"), api.get("/api/inbox"),
  ]);
  const mine = cands.filter((c) => c.source_ids.includes(recordId));
  const isFile = src.source_type === "pdf";
  const item = inbox.find((i) => i.record_id === recordId);
  let blobUrl = null;
  const body = isFile ? `
    <div class="tabs" role="tablist" style="margin-bottom:10px"><button class="active" data-vtab="original">Original</button><button data-vtab="text">Text Studyspace read</button></div>
    <div data-vpane="original"><div class="pdf-frame"><div class="loading"><span class="spinner"></span></div></div></div>
    <div data-vpane="text" hidden><div class="message-body">${highlightEvidence(src.body_text, mine.map((c) => c.evidence))}</div></div>`
    : `<div class="message-body tall">${highlightEvidence(src.body_text, mine.map((c) => c.evidence))}</div>`;
  const html = `
    <div class="viewer">
      <div class="viewer-main">
        <dl class="meta-list" style="margin-top:0">
          ${isFile ? `<div><dt>File</dt><dd>${esc(src.meta.filename || src.subject)} · ${esc(src.meta.pages ?? "?")} page(s)</dd></div>`
            : `<div><dt>From</dt><dd>${esc(src.sender || "—")}</dd></div>`}
          <div><dt>${isFile ? "Added" : "Received"}</dt><dd>${esc(fmtDateTime(src.received_at) || "—")}${src.course_code ? ` · ${esc(src.course_code)}` : ""}</dd></div>
          ${item ? `<div><dt>What it asks of you</dt><dd>${labelChips(item.labels)} <span class="small muted">${esc(item.reasons.join("; "))}</span></dd></div>` : ""}
        </dl>
        ${body}
        ${mine.length ? `<p class="tiny muted" style="margin:8px 0 0"><mark class="evidence">Highlighted</mark> sentences are where tasks were found.</p>` : ""}
      </div>
      <aside class="viewer-side">
        <p class="side-title">Found here</p>
        ${foundList(mine)}
        ${mine.some((c) => c.status === "pending") ? `<a class="btn small primary" style="margin-top:12px" href="#/review?focus=${encodeURIComponent(mine.find((c) => c.status === "pending").candidate_id)}" data-close>Check these tasks →</a>` : ""}
        <div class="stack" style="gap:8px;margin-top:18px">
          ${item?.labels.includes("reply") ? `<a class="btn small" href="#/replies?open=${encodeURIComponent(recordId)}" data-close>Draft a reply</a>` : ""}
          <a class="btn small" href="#/privacy?open=${encodeURIComponent(recordId)}" data-close>What a model would see</a>
          <button class="btn small danger" data-remove>Remove from Studyspace</button>
        </div>
      </aside>
    </div>`;
  const p = modal(src.subject || (isFile ? "Course file" : "Message"), html, { wide: true });
  const dlg = document.getElementById("modal");
  dlg.querySelectorAll("[data-vtab]").forEach((b) => b.addEventListener("click", () => {
    dlg.querySelectorAll("[data-vtab]").forEach((x) => x.classList.toggle("active", x === b));
    dlg.querySelectorAll("[data-vpane]").forEach((x) => (x.hidden = x.dataset.vpane !== b.dataset.vtab));
  }));
  dlg.querySelector("[data-remove]").addEventListener("click", async () => {
    if (!(await confirmDialog("Remove this source?", "Studyspace forgets it and any unconfirmed tasks found only in it. Tasks you already confirmed stay.", "Remove", true))) return;
    try { await api.del(`/api/sources/${encodeURIComponent(recordId)}`); toast("Removed."); ctx.refresh(); } catch (err) { showError(err); }
  });
  if (isFile && src.meta.file_id) {
    try {
      blobUrl = await api.blobUrl(`/api/files/${encodeURIComponent(src.meta.file_id)}/raw`);
      const frame = dlg.querySelector(".pdf-frame");
      if (frame) frame.innerHTML = `<iframe src="${blobUrl}" title="${esc(src.subject || "PDF")}"></iframe><a class="btn tiny" href="${blobUrl}" target="_blank" rel="noopener" style="margin-top:8px">Open in a new tab</a>`;
    } catch (err) {
      const frame = dlg.querySelector(".pdf-frame");
      if (frame) frame.innerHTML = `<div class="empty">The original file is not available.</div>`;
    }
  }
  await p;
  if (blobUrl) URL.revokeObjectURL(blobUrl);
}

export function openClass(item) {
  modal(item.label || "Class", `
    <dl class="meta-list" style="margin:0">
      <div><dt>When</dt><dd>${esc(fmtDateTime(item.start))} – ${esc(fmtRange(item.start, item.end).split("–")[1])}</dd></div>
      <div><dt>Source</dt><dd>${item.origin === "manual" ? "Added by you" : "Your timetable file"}</dd></div>
    </dl>
    <p class="small muted" style="margin:0">Studyspace never plans study over this time. Change your free hours on the Study plan page.</p>`,
  { actions: [{ label: "Close", value: true }] });
}

// ---- add dialogs ----------------------------------------------------------------------------
export async function uploadFiles(files, ctx) {
  const form = new FormData();
  [...files].forEach((f) => form.append("files", f));
  const r = await api.upload("/api/import", form);
  const ex = await api.post("/api/extract");
  const added = r.files.reduce((n, f) => n + (f.added || 0) + (f.updated || 0), 0);
  const dup = r.files.reduce((n, f) => n + (f.duplicate || 0), 0);
  const slots = r.files.reduce((n, f) => n + (f.slots || 0), 0);
  const errors = r.files.filter((f) => f.error).map((f) => `${f.filename}: ${f.error}`);
  const pending = ex.candidates.filter((c) => c.status === "pending").length;
  toast([
    added ? `${added} new item(s) read` : "",
    dup ? `${dup} already here` : "",
    slots ? `${slots} calendar entries` : "",
    `${pending} task(s) waiting for your check`,
    errors.length ? errors.join("; ") : "",
  ].filter(Boolean).join(" · "), errors.length && !added ? "error" : "info");
  ctx.refresh();
}

const ADD = {
  email: { title: "Add messages", accept: ".eml,.csv,.txt", hint: "Saved emails (.eml) from Outlook or Gmail, or a CSV export. You can also paste a Teams or WhatsApp message.", paste: true },
  timetable: { title: "Add to your timetable", accept: ".ics,.json", hint: "Your timetable as an .ics file (NUSMods › Download › iCal). Adding a new file replaces the old timetable.", commitment: true },
  files: { title: "Add course files", accept: ".pdf,.txt", hint: "Lecture slides, assignment briefs or reading lists as PDF. Studyspace reads the deadlines in them; the original stays on this computer." },
};

export function addDialog(kind, ctx) {
  const cfg = ADD[kind];
  const now = ctx.workspace?.now;
  const tabs = [["upload", "Upload files"], ...(cfg.paste ? [["paste", "Paste text"]] : []), ...(cfg.commitment ? [["commit", "One-off commitment"]] : [])];
  const html = `
    ${tabs.length > 1 ? `<div class="tabs">${tabs.map(([k, l], i) => `<button data-atab="${k}" class="${i === 0 ? "active" : ""}">${l}</button>`).join("")}</div>` : ""}
    <div data-apane="upload">
      <label class="dropzone" id="add-drop">
        <input type="file" multiple accept="${cfg.accept}" class="sr-only" id="add-input">
        <strong>Drop files here or choose them</strong>${esc(cfg.hint)}
      </label>
    </div>
    ${cfg.paste ? `<div data-apane="paste" hidden class="form-grid">
      <label class="field">Subject or source <input type="text" id="add-subject" placeholder="e.g. Teams message from groupmate"></label>
      <label class="field">Received · SGT <input type="datetime-local" id="add-time" value="${esc(toLocalInput(now))}"></label>
      <label class="field full">Message <textarea id="add-text" placeholder="Paste the message"></textarea></label>
      <div class="full row between"><span class="tiny muted">"This Friday" and similar are read from the received time.</span><button class="btn primary" id="add-paste">Add message</button></div>
    </div>` : ""}
    ${cfg.commitment ? `<div data-apane="commit" hidden class="form-grid">
      <label class="field">What <input type="text" id="c-label" placeholder="e.g. Part-time work"></label>
      <label class="field">Day <input type="date" id="c-day" value="${esc(now ? sgDate(now) : "")}"></label>
      <label class="field">Start <input type="time" id="c-start" value="14:00"></label>
      <label class="field">End <input type="time" id="c-end" value="16:00"></label>
      <div class="full row between"><a class="btn small ghost" href="#/plan?edit=hours" data-close>Edit your free hours instead</a><button class="btn primary" id="c-add">Add commitment</button></div>
    </div>` : ""}`;
  const p = modal(cfg.title, html, { wide: false });
  const dlg = document.getElementById("modal");
  dlg.querySelectorAll("[data-atab]").forEach((b) => b.addEventListener("click", () => {
    dlg.querySelectorAll("[data-atab]").forEach((x) => x.classList.toggle("active", x === b));
    dlg.querySelectorAll("[data-apane]").forEach((x) => (x.hidden = x.dataset.apane !== b.dataset.atab));
  }));
  const zone = dlg.querySelector("#add-drop"), input = dlg.querySelector("#add-input");
  const go = async (files) => {
    if (!files.length) return;
    zone.classList.add("over");
    zone.querySelector("strong").textContent = "Reading…";
    try { await uploadFiles(files, ctx); dlg.close(); } catch (err) { showError(err); } finally { zone.classList.remove("over"); }
  };
  input.addEventListener("change", () => go(input.files));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); go(e.dataTransfer.files); });
  dlg.querySelector("#add-paste")?.addEventListener("click", async () => {
    const text = dlg.querySelector("#add-text").value.trim();
    if (!text) return toast("Paste a message first.", "error");
    try {
      const r = await api.post("/api/import/text", { text, subject: dlg.querySelector("#add-subject").value || null, received_at: fromLocalInput(dlg.querySelector("#add-time").value) });
      const ex = await api.post("/api/extract");
      const found = ex.candidates.filter((c) => c.status === "pending" && r.record_ids.some((id) => c.source_ids.includes(id))).length;
      toast(r.duplicate ? "This message was already here." : `Added. ${found} task(s) found in it.`);
      dlg.close();
      ctx.refresh();
    } catch (err) { showError(err); }
  });
  dlg.querySelector("#c-add")?.addEventListener("click", async () => {
    const day = dlg.querySelector("#c-day").value, s = dlg.querySelector("#c-start").value, e = dlg.querySelector("#c-end").value;
    if (!day || !s || !e || e <= s) return toast("Choose a day and a start before the end.", "error");
    try {
      await api.post("/api/calendar/busy", { start: `${day}T${s}:00+08:00`, end: `${day}T${e}:00+08:00`, label: dlg.querySelector("#c-label").value || "Busy" });
      toast("Added. Your plan will keep this time free.");
      dlg.close();
      ctx.refresh();
    } catch (err) { showError(err); }
  });
  return p;
}

// ---- sync (planned) -------------------------------------------------------------------------
const SYNC = {
  email: {
    title: "Sync your email",
    services: [["Outlook (Microsoft 365)", "NUS email"], ["Gmail", "personal email"]],
    what: "Studyspace will read new course emails as they arrive, find tasks and deadlines, and ask you to check them. The originals stay on this computer.",
    manual: ["Outlook: drag an email to your desktop to save it as .eml.", "Gmail: open the email › ⋮ › Download message.", "Then add the .eml files with +."],
  },
  timetable: {
    title: "Sync your timetable",
    services: [["NUSMods", "class timetable"], ["Outlook Calendar", "meetings and events"], ["Google Calendar", "personal calendar"]],
    what: "Studyspace will keep your classes and meetings up to date so the plan never uses that time. Only start and end times are needed.",
    manual: ["NUSMods › Download › iCal file (.ics).", "Then add it with +. A new file replaces the old timetable."],
  },
  files: {
    title: "Sync course files",
    services: [["Microsoft Teams files", "group project folders"], ["OneDrive", "your own files"]],
    what: "Studyspace will pick up new briefs and slides from the folders you choose and read their deadlines. Canvas and other learning systems are outside this project.",
    manual: ["Download the PDF from where your course shares it.", "Then add it with +."],
  },
};

export function syncDialog(kind, ctx) {
  const cfg = SYNC[kind];
  return modal(cfg.title, `
    <div class="alert purple"><strong>Automatic sync is not available yet</strong><span>${esc(cfg.what)}</span></div>
    <div class="stack" style="gap:8px">
      ${cfg.services.map(([name, sub]) => `<div class="row between connector"><span><b>${esc(name)}</b><span class="tiny muted"> · ${esc(sub)}</span></span><span class="chip outline">Planned</span></div>`).join("")}
    </div>
    <div><p class="side-title" style="margin:6px 0 8px">Until then</p>
      <ol class="small muted" style="margin:0;padding-left:18px;display:grid;gap:4px">${cfg.manual.map((m) => `<li>${esc(m)}</li>`).join("")}</ol></div>
    <p class="tiny muted" style="margin:0">Whatever the source, nothing is sent on your behalf, and only cleaned, redacted text would ever reach a language model.</p>`, {
    actions: [{ label: "Close", value: null }, { label: "Add manually", primary: true, onClick: () => { setTimeout(() => addDialog(kind, ctx), 0); return true; } }],
  });
}

export function senderLine(i) {
  return `${esc(senderName(i.sender))}${i.course_code ? ` · ${esc(i.course_code)}` : ""}`;
}
