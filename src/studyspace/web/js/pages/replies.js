// 04 Replies (gate 3): drafts in the student's style. Studyspace never sends; the student reads, then sends.
import { api } from "../api.js";
import { busy, esc, fmtDateTime, senderName, showError, toast } from "../util.js";

let selected = null;

export async function render(root, ctx, params) {
  const inbox = await api.get("/api/inbox");
  const waiting = inbox.filter((i) => i.labels.includes("reply"));
  const others = inbox.filter((i) => !i.labels.includes("reply") && i.sender_kind !== "system" && !i.labels.includes("newsletter"));
  selected = params.get("open") || (waiting.some((w) => w.record_id === selected) ? selected : waiting[0]?.record_id) || null;

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Reply when it suits you</p>
        <h1>Short replies, in your own words.</h1>
        <p class="lede">Drafts follow the greeting and sign-off you usually use. You read every draft and send it yourself.</p>
      </div>
    </div>
    <div class="grid wide-side">
      <div class="stack" id="draft-area"><section class="card"><div class="loading"><span class="spinner"></span></div></section></div>
      <aside class="stack">
        <section class="card">
          <div class="card-head"><h2>Waiting for you</h2><span class="chip amber">${waiting.length}</span></div>
          <div class="list">${waiting.map(item).join("") || `<div class="empty">No one is waiting for a reply.</div>`}</div>
        </section>
        ${others.length ? `<section class="card"><div class="card-head"><h2>Other messages</h2></div>
          <div class="list">${others.slice(0, 8).map(item).join("")}</div></section>` : ""}
        <section class="card soft"><div class="card-body small muted">
          <b style="color:var(--ink)">Never sent automatically.</b> “Open in mail app” starts a new email in your own mail program with this text; nothing leaves Studyspace.
        </div></section>
      </aside>
    </div>`;

  root.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { selected = b.dataset.open; ctx.go("replies", `open=${encodeURIComponent(selected)}`); }));
  const area = root.querySelector("#draft-area");
  if (!selected) {
    area.innerHTML = `<section class="card"><div class="empty"><strong>Nothing to answer</strong>Messages that ask you something appear on the right.</div></section>`;
    return;
  }
  await showDraft(area, ctx, inbox.find((i) => i.record_id === selected), false);
}

function item(i) {
  return `<button class="msg ${selected === i.record_id ? "active" : ""}" data-open="${esc(i.record_id)}" style="grid-template-columns:minmax(0,1fr) auto">
    <span style="min-width:0"><span class="subject">${esc(senderName(i.sender))}</span><span class="snippet">${esc(i.subject || "")}</span></span>
    <span class="when">${i.draft_status === "reviewed" ? `<span class="chip green">ready</span>` : esc(fmtDateTime(i.received_at))}</span></button>`;
}

async function showDraft(area, ctx, msg, regenerate) {
  area.innerHTML = `<section class="card"><div class="loading"><span class="spinner"></span></div></section>`;
  try {
    const [d, src] = await Promise.all([
      api.get(`/api/drafts/${encodeURIComponent(msg.record_id)}${regenerate ? "?regenerate=true" : ""}`),
      api.get(`/api/sources/${encodeURIComponent(msg.record_id)}`),
    ]);
    const reviewed = d.status === "reviewed";
    area.innerHTML = `
    <section class="card">
      <div class="card-head"><h2>Reply to ${esc(senderName(src.sender))}</h2>
        <span class="chip ${reviewed ? "green" : ""}">${reviewed ? "Read and ready" : "Draft"}</span></div>
      <div class="card-body stack">
        ${d.warnings.map((w) => `<div class="alert amber"><strong>Check before sending</strong><span>${esc(w.message)}</span></div>`).join("")}
        <div class="form-grid">
          <label class="field">To <input type="text" value="${esc(d.to)}" readonly></label>
          <label class="field">Subject <input type="text" id="d-subject" value="${esc(d.subject)}"></label>
          <label class="field full">Message <textarea id="d-body" style="min-height:220px">${esc(d.body)}</textarea></label>
        </div>
        ${d.slots?.length && d.intent === "availability" ? `<div><span class="meta-label">Free times you could offer</span><div class="row" style="margin-top:6px">${d.slots.map((s) => `<button class="btn tiny" data-slot="${esc(fmtDateTime(s.start))}–${esc(fmtDateTime(s.end).split(", ")[1])}">${esc(fmtDateTime(s.start))}</button>`).join("")}</div></div>` : ""}
        <label class="check"><input type="checkbox" id="d-check" ${reviewed ? "checked" : ""}> I have read this draft and will send it myself</label>
        <div class="row">
          <button class="btn primary" id="d-copy" ${reviewed ? "" : "disabled"}>Copy text</button>
          <a class="btn" id="d-mail" ${reviewed ? "" : 'aria-disabled="true" style="pointer-events:none;opacity:.5"'} href="${mailto(d)}">Open in mail app</a>
          <span class="spacer"></span>
          <button class="btn small" id="d-save">Save edits</button>
          <button class="btn small ghost" id="d-regen">New draft</button>
        </div>
        <p class="tiny muted" style="margin:0">Drafted ${d.mode === "model" ? "by the language model from cleaned, redacted text" : "on this computer from a template"} · intent: ${esc(d.intent)}</p>
      </div>
    </section>
    <section class="card"><div class="card-body">
      <p class="side-title">Their message</p>
      <div class="message-body">${esc(src.body_text)}</div>
    </div></section>`;

    const body = area.querySelector("#d-body"), subject = area.querySelector("#d-subject"), check = area.querySelector("#d-check");
    const setReady = (on) => {
      area.querySelector("#d-copy").disabled = !on;
      const mail = area.querySelector("#d-mail");
      mail.style.pointerEvents = on ? "" : "none";
      mail.style.opacity = on ? "" : ".5";
      mail.setAttribute("aria-disabled", String(!on));
      mail.href = mailto({ ...d, subject: subject.value, body: body.value });
    };
    const markEdited = () => { if (check.checked) { check.checked = false; setReady(false); } };
    body.addEventListener("input", markEdited);
    subject.addEventListener("input", markEdited);
    area.querySelectorAll("[data-slot]").forEach((b) => b.addEventListener("click", () => {
      body.setRangeText(`\n- ${b.dataset.slot}`, body.selectionStart, body.selectionEnd, "end");
      markEdited();
      body.focus();
    }));
    check.addEventListener("change", async () => {
      try {
        if (check.checked) {
          await api.put(`/api/drafts/${encodeURIComponent(msg.record_id)}`, { body: body.value, subject: subject.value });
          await api.post(`/api/drafts/${encodeURIComponent(msg.record_id)}/reviewed`);
        }
        setReady(check.checked);
        ctx.refreshShell();
      } catch (err) { showError(err); check.checked = false; }
    });
    area.querySelector("#d-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(body.value); toast("Copied. Paste it into your email."); }
      catch { body.select(); toast("Select-all done. Press Ctrl/Cmd+C to copy."); }
    });
    area.querySelector("#d-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      try { await api.put(`/api/drafts/${encodeURIComponent(msg.record_id)}`, { body: body.value, subject: subject.value }); toast("Saved."); }
      catch (err) { showError(err); }
    }));
    area.querySelector("#d-regen").addEventListener("click", () => showDraft(area, ctx, msg, true));
  } catch (err) {
    area.innerHTML = `<section class="card empty"><strong>Could not draft a reply</strong>${esc(err.message)}</section>`;
  }
}

function mailto(d) {
  return `mailto:${encodeURIComponent(d.to || "")}?subject=${encodeURIComponent(d.subject || "")}&body=${encodeURIComponent(d.body || "")}`;
}
