// 06 Privacy & data: what would leave the computer, and what did.
import { api } from "../api.js";
import { esc, fmtDateTime, showError } from "../util.js";

export async function render(root, ctx, params) {
  const [sources, log] = await Promise.all([api.get("/api/sources"), api.get("/api/privacy/log")]);
  const pick = params.get("open") || sources[sources.length - 1]?.record_id || "";
  const offline = log.provider === "offline";

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Your messages stay yours</p>
        <h1>See exactly what leaves this computer.</h1>
        <p class="lede">Originals stay in the local database. A model would only ever receive cleaned, redacted text, through one gateway that logs every call.</p>
      </div>
    </div>
    <div class="grid">
      <div class="stack">
        <section class="card">
          <div class="card-head"><h2>Preview a message</h2>
            <select id="p-pick" style="max-width:360px" aria-label="Message">${sources.map((s) => `<option value="${esc(s.record_id)}" ${s.record_id === pick ? "selected" : ""}>${esc(s.subject || s.record_id)}</option>`).join("")}</select></div>
          <div class="card-body" id="p-compare">${sources.length ? `<div class="loading"><span class="spinner"></span></div>` : `<div class="empty">Add messages to preview them.</div>`}</div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Model calls</h2><span class="chip ${offline ? "green" : "amber"}">${offline ? "Offline: nothing sent" : esc(log.provider)}</span></div>
          ${log.calls.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Purpose</th><th>Text sent</th></tr></thead><tbody>
            ${log.calls.map((c) => `<tr><td class="small">${esc(fmtDateTime(c.created_at))}</td><td>${esc(c.purpose)}</td><td class="small">${esc(c.sent_text.slice(0, 240))}</td></tr>`).join("")}</tbody></table></div>`
          : `<div class="empty">${offline ? "No model is connected. Extraction and drafts run on this computer with rules and templates." : "No calls yet."}</div>`}
        </section>
      </div>
      <aside class="stack">
        <section class="card"><div class="card-body">
          <p class="side-title">Before anything is sent</p>
          <ol class="steps">
            <li><span><b>Clean</b>Quoted earlier replies, signatures and links are removed.</span></li>
            <li><span><b>Redact</b>Names, student IDs, emails, phone numbers and passwords become placeholders.</span></li>
            <li><span><b>Send</b>Only that text goes to one provider, with the key kept in a local .env file.</span></li>
            <li><span><b>Log</b>Every call is listed here. Names are put back only on this computer.</span></li>
          </ol>
        </div></section>
        <section class="card"><div class="card-body">
          <p class="side-title">Where your data is</p>
          <p class="small muted" style="margin:0 0 10px">One local SQLite file:</p>
          <code class="small" style="word-break:break-all">${esc(log.database)}</code>
          <p class="small muted" style="margin:12px 0">The hosted demo only uses fictional data. Nothing here is sent to the course or to teammates.</p>
          <button class="btn small danger" data-global="reset">Delete all data in this workspace</button>
        </div></section>
      </aside>
    </div>`;

  const show = async (id) => {
    const box = root.querySelector("#p-compare");
    if (!id) return;
    box.innerHTML = `<div class="loading"><span class="spinner"></span></div>`;
    try {
      const r = await api.post("/api/privacy/preview", { record_id: id });
      const counts = Object.entries(r.replaced).map(([k, v]) => `${v} ${k.replace("_", " ")}${v > 1 ? "s" : ""}`).join(", ");
      box.innerHTML = `
        <div class="compare">
          <div><span class="meta-label">Stored on this computer</span><div class="message-body" style="margin-top:6px">${esc(r.original)}</div></div>
          <div><span class="meta-label">What a model would receive</span><div class="message-body" style="margin-top:6px">${highlight(r.would_send)}</div></div>
        </div>
        <p class="small muted" style="margin:12px 0 0">${counts ? `Replaced: ${esc(counts)}.` : "No personal details found."} Removed text (quotes, signatures) is not shown on the right.</p>`;
    } catch (err) { showError(err); }
  };
  root.querySelector("#p-pick")?.addEventListener("change", (e) => show(e.target.value));
  show(pick);
}

function highlight(text) {
  return esc(text).replace(/\[(NAME_\d+|EMAIL|PHONE|STUDENT_ID|SECRET|LINK)\]/g, '<mark class="redacted">[$1]</mark>');
}
