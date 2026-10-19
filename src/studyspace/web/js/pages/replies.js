// Replies (gate 3): their message beside your reply. You give the points, Studyspace writes them up in your
// style; you read it and send it yourself. Nothing is ever sent by the app.
import { api } from "../api.js";
import { icon } from "../icons.js";
import { busy, esc, fmtDateTime, initials, senderName, showError, toast } from "../util.js";

let selected = null;
const ROLE = { staff: ["Teaching staff", "blue"], peer: ["Classmate", "green"], external: ["Outside the university", "amber"], system: ["Automated", "grey"], unknown: ["", "grey"] };
const QUICK = [
  ["Yes, will do", "yes, will do it by then"],
  ["Need more time", "could I have until next week? the other deadlines are close"],
  ["Thanks, noted", "thanks, noted"],
  ["Ask a question", "quick question: "],
];

export async function render(root, ctx, params) {
  const inbox = await api.get("/api/inbox");
  const waiting = inbox.filter((i) => i.labels.includes("reply"));
  const people = inbox.filter((i) => !i.labels.includes("reply") && i.sender_kind !== "system" && !i.labels.includes("newsletter"));
  selected = params.get("open") || (inbox.some((w) => w.record_id === selected) ? selected : waiting[0]?.record_id) || null;

  root.innerHTML = `
    <div class="page-head">
      <div><h1>Replies</h1><p class="lede">Their message on the left, your reply on the right. Give the points; Studyspace writes them up in your style. You send it yourself.</p></div>
    </div>
    <div class="replies-layout">
      <aside class="card convo-list">
        <div class="convo-group">Waiting for you <span class="chip amber">${waiting.length}</span></div>
        ${waiting.map(item).join("") || `<p class="small muted" style="padding:0 16px">No one is waiting for an answer.</p>`}
        ${people.length ? `<div class="convo-group">Other people</div>${people.slice(0, 10).map(item).join("")}` : ""}
      </aside>
      <div id="compose">${selected ? `<div class="skeleton"><div></div><div></div></div>` : `<section class="card"><div class="calm big">${icon("reply", 28)}<div><b>Nothing to answer</b><span>When someone asks you something, it shows up here.</span></div></div></section>`}</div>
    </div>`;

  root.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { selected = b.dataset.open; ctx.go("replies", `open=${encodeURIComponent(selected)}`); }));
  if (selected) await compose(root.querySelector("#compose"), ctx, inbox.find((i) => i.record_id === selected), false);
}

function item(i) {
  const [role] = ROLE[i.sender_kind] || ROLE.unknown;
  const status = i.draft_status === "reviewed" ? `<span class="chip green">ready</span>` : i.draft_status === "draft" ? `<span class="chip">draft</span>` : "";
  return `<button class="convo ${selected === i.record_id ? "active" : ""}" data-open="${esc(i.record_id)}">
    <span class="avatar small k-${esc(i.sender_kind)}">${esc(initials(senderName(i.sender)))}</span>
    <span class="convo-main"><b>${esc(senderName(i.sender))}</b><span>${esc(i.subject || "")}</span></span>
    <span class="convo-side">${status || `<span class="tiny muted">${esc(role)}</span>`}</span>
  </button>`;
}

function highlightAsks(body, asks) {
  let html = esc(body);
  for (const a of asks) {
    const words = esc(a).split(/\s+/).filter(Boolean);
    if (words.length < 2) continue;
    const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
    try { html = html.replace(new RegExp(pattern), (m) => `<mark class="ask">${m}</mark>`); } catch { /* ignore */ }
  }
  return html;
}

async function compose(area, ctx, msg, regenerate) {
  try {
    const [d, src] = await Promise.all([
      api.get(`/api/drafts/${encodeURIComponent(msg.record_id)}${regenerate ? "?regenerate=true" : ""}`),
      api.get(`/api/sources/${encodeURIComponent(msg.record_id)}`),
    ]);
    draw(area, ctx, msg, d, src);
  } catch (err) {
    area.innerHTML = `<section class="card empty"><strong>Could not prepare a reply</strong>${esc(err.message)}</section>`;
  }
}

function draw(area, ctx, msg, d, src) {
  d = { asks: [], changes: [], tone: "friendly", points: "", slots: [], warnings: [], ...d };  // drafts saved by older versions
  const [role, roleTone] = ROLE[msg.sender_kind] || ROLE.unknown;
  const reviewed = d.status === "reviewed";
  const offline = d.mode !== "model";
  area.innerHTML = `
  <div class="compose">
    <section class="card their">
      <div class="msg-head">
        <span class="avatar k-${esc(msg.sender_kind)}">${esc(initials(senderName(src.sender)))}</span>
        <div><b>${esc(senderName(src.sender))}</b>${role ? ` <span class="chip ${roleTone}">${esc(role)}</span>` : ""}<span class="tiny muted">${esc(fmtDateTime(src.received_at))}</span></div>
      </div>
      <h3 class="msg-subject">${esc(src.subject || "(no subject)")}</h3>
      ${d.asks.length ? `<div class="asks"><span class="tc-label">They ask</span><ul>${d.asks.map((a) => `<li>${icon("reply", 13)}<span>${esc(a)}</span></li>`).join("")}</ul></div>` : ""}
      <div class="message-body tall">${highlightAsks(src.body_text, d.asks)}</div>
    </section>

    <section class="card yours">
      <div class="step"><span class="step-n">1</span><b>What do you want to say?</b><span class="tiny muted">optional · short notes are fine</span></div>
      <textarea id="points" class="points" placeholder="e.g. ok will finish by thu night, will push to github">${esc(d.points || "")}</textarea>
      <div class="seg small quick">${QUICK.map(([label, text]) => `<button class="seg-btn" data-quick="${esc(text)}">${esc(label)}</button>`).join("")}
        ${d.slots?.length ? `<button class="seg-btn" data-times>Offer my free times</button>` : ""}</div>
      <div class="step"><span class="step-n">2</span><b>Tone</b></div>
      <div class="seg" id="tone">${["friendly", "formal", "brief"].map((t) => `<button class="seg-btn ${d.tone === t ? "on" : ""}" data-tone="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>
      <button class="btn primary write-btn" id="write">${icon("spark", 15)} Write my reply</button>

      <div class="step"><span class="step-n">3</span><b>Your reply</b>
        <span class="chip ${offline ? "grey" : "green"}" title="${offline ? "No language model is connected; the reply is built from your notes with rules and your usual greeting and sign-off." : "Written by the language model from cleaned, redacted text."}">${offline ? "Offline · template" : "AI draft"}</span></div>
      ${d.changes?.length ? `<div class="changes"><span class="tiny muted">From your notes:</span>${d.changes.map((c) => `<span class="chip outline">${esc(c)}</span>`).join("")}</div>` : ""}
      <div class="form-grid">
        <label class="field">To <input type="text" value="${esc(d.to)}" readonly></label>
        <label class="field">Subject <input type="text" id="d-subject" value="${esc(d.subject)}"></label>
      </div>
      <textarea id="d-body" class="reply-body">${esc(d.body)}</textarea>
      ${d.warnings.map((w) => `<div class="alert amber"><strong>${icon("flag", 13)} Check before sending</strong><span>${esc(w.message)}</span></div>`).join("")}
      <div class="send-row">
        <label class="check"><input type="checkbox" id="d-check" ${reviewed ? "checked" : ""}> I've read it and will send it myself</label>
        <div class="row">
          <button class="btn small" id="d-save">Save</button>
          <button class="btn small" id="d-copy" ${reviewed ? "" : "disabled"}>Copy</button>
          <a class="btn small primary" id="d-mail" href="${mailto(d)}" ${reviewed ? "" : 'aria-disabled="true" tabindex="-1"'}>Open in mail app</a>
        </div>
      </div>
      <p class="tiny muted" style="margin:0">Studyspace never sends email. “Open in mail app” starts a new message in your own email program.</p>
    </section>
  </div>`;

  let tone = d.tone;
  const points = area.querySelector("#points"), body = area.querySelector("#d-body"), subject = area.querySelector("#d-subject"), check = area.querySelector("#d-check");
  const mail = area.querySelector("#d-mail");
  const setReady = (on) => {
    area.querySelector("#d-copy").disabled = !on;
    mail.classList.toggle("disabled", !on);
    mail.setAttribute("aria-disabled", String(!on));
    mail.href = mailto({ ...d, subject: subject.value, body: body.value });
  };
  setReady(reviewed);
  const edited = () => { if (check.checked) { check.checked = false; setReady(false); } };
  body.addEventListener("input", edited);
  subject.addEventListener("input", edited);
  area.querySelector("#tone").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tone]");
    if (!b) return;
    tone = b.dataset.tone;
    area.querySelectorAll("[data-tone]").forEach((x) => x.classList.toggle("on", x === b));
  });
  area.querySelectorAll("[data-quick]").forEach((b) => b.addEventListener("click", () => {
    points.value = points.value ? `${points.value.trim()}\n${b.dataset.quick}` : b.dataset.quick;
    points.focus();
  }));
  const write = async (pts) => {
    const r = await api.post(`/api/drafts/${encodeURIComponent(msg.record_id)}/compose`, { points: pts, tone });
    draw(area, ctx, msg, r, src);
    area.querySelector("#d-body").classList.add("flash-in");
    toast(pts ? "Reply written from your notes. Read it before sending." : "Reply drafted. Read it before sending.");
  };
  area.querySelector("#write").addEventListener("click", (e) => busy(e.currentTarget, async () => { try { await write(points.value.trim() || null); } catch (err) { showError(err); } }));
  area.querySelector("[data-times]")?.addEventListener("click", () => write(null).catch(showError));
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
    catch { body.select(); toast("Selected. Press Ctrl/Cmd+C to copy."); }
  });
  mail.addEventListener("click", (e) => { if (mail.classList.contains("disabled")) { e.preventDefault(); toast("Tick “I've read it” first.", "error"); } });
  area.querySelector("#d-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try { await api.put(`/api/drafts/${encodeURIComponent(msg.record_id)}`, { body: body.value, subject: subject.value }); toast("Saved."); }
    catch (err) { showError(err); }
  }));
}

function mailto(d) {
  return `mailto:${encodeURIComponent(d.to || "")}?subject=${encodeURIComponent(d.subject || "")}&body=${encodeURIComponent(d.body || "")}`;
}
