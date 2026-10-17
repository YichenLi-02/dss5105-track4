// 07 Settings: who the student is (for drafts and redaction), demo data, and how to bring real data in.
import { api } from "../api.js";
import { busy, esc, showError, toast } from "../util.js";

export async function render(root, ctx) {
  const s = await api.get("/api/settings");
  const health = await api.get("/api/health");
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Settings</p>
        <h1>Make it yours.</h1>
        <p class="lede">Your name is used to sign reply drafts and is always redacted before anything could be sent.</p>
      </div>
    </div>
    <div class="grid">
      <div class="stack">
        <section class="card">
          <div class="card-head"><h2>About you</h2></div>
          <div class="card-body stack">
            <div class="form-grid">
              <label class="field">Name <input type="text" id="s-name" value="${esc(s.name || "")}"></label>
              <label class="field">University email <input type="email" id="s-email" value="${esc(s.email || "")}" placeholder="you@u.nus.edu"><span class="hint">Used to tell classmates from outside senders.</span></label>
            </div>
            <div><button class="btn primary" id="s-save">Save</button></div>
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Bringing in real messages</h2></div>
          <div class="card-body small muted stack" style="gap:8px">
            <p style="margin:0"><b style="color:var(--ink)">Outlook:</b> drag an email from Outlook to your desktop (saved as .eml), then drop it on the Inbox page.</p>
            <p style="margin:0"><b style="color:var(--ink)">Gmail:</b> open the email › ⋮ › Download message (.eml).</p>
            <p style="margin:0"><b style="color:var(--ink)">Timetable:</b> NUSMods › Download › iCal file (.ics).</p>
            <p style="margin:0"><b style="color:var(--ink)">Teams or WhatsApp:</b> copy the message and paste it on the Inbox page.</p>
            <p style="margin:0">Direct mailbox connection is planned once the university's access rules are confirmed.</p>
          </div>
        </section>
      </div>
      <aside class="stack">
        <section class="card"><div class="card-body">
          <p class="side-title">Demo</p>
          <p class="small muted" style="margin:0 0 12px">A fictional student (Jordan Lee) with 25 emails, a NUSMods-style timetable and free hours. The clock is fixed at Monday 12 Oct 2026, 08:00.</p>
          <button class="btn primary small" data-global="load-demo">Load demo student</button>
        </div></section>
        <section class="card"><div class="card-body">
          <p class="side-title">System</p>
          <div class="kv" style="border-top:0"><span>Version</span><b>${esc(health.version)}</b></div>
          <div class="kv"><span>Language model</span><b>${health.llm_online ? esc(health.llm_provider) : "none (offline)"}</b></div>
          <div class="kv"><span>Workspace</span><b>${esc(api.workspace())}</b></div>
          <a class="btn small" href="/docs" target="_blank" rel="noopener" style="margin-top:10px">API documentation</a>
        </div></section>
      </aside>
    </div>`;

  root.querySelector("#s-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      await api.put("/api/settings", { name: root.querySelector("#s-name").value, email: root.querySelector("#s-email").value });
      toast("Saved.");
      ctx.refreshShell();
    } catch (err) { showError(err); }
  }));
}
