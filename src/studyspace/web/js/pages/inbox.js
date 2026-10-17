// All messages: the full email list behind the Email card on the Sources page.
import { api } from "../api.js";
import { esc, fmtDateTime } from "../util.js";
import { ICON, addDialog, labelChips, openSource, senderLine, syncDialog } from "../sources-common.js";

const FILTERS = [["all", "All"], ["task", "Tasks"], ["reply", "Replies"], ["event", "Events"], ["info", "Info"], ["newsletter", "Newsletters"]];
let filter = "all";
let query = "";

export async function render(root, ctx, params) {
  const items = await api.get("/api/inbox");
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, k === "all" ? items.length : items.filter((i) => i.labels.includes(k)).length]));

  root.innerHTML = `
    <div class="page-head">
      <div>
        <a class="btn small ghost" href="#/sources" style="padding-left:0;margin-bottom:6px">← Sources</a>
        <h1>All messages</h1>
        <p class="lede">Every email and message Studyspace has read, newest first, with what each one asks of you.</p>
      </div>
      <div class="row">
        <button class="btn small" data-sync="email">${ICON.sync} Sync</button>
        <button class="btn small primary" data-add="email">${ICON.plus} Add messages</button>
      </div>
    </div>
    <section class="card">
      <div class="card-head">
        <div class="filters" role="group" aria-label="Filter messages">
          ${FILTERS.map(([k, label]) => `<button data-filter="${k}" class="${filter === k ? "active" : ""}">${label}<span class="n">${counts[k]}</span></button>`).join("")}
        </div>
        <input type="text" id="search" placeholder="Search subject, sender or course" value="${esc(query)}" style="max-width:280px">
      </div>
      <div class="list" id="msg-list"></div>
    </section>`;

  const list = root.querySelector("#msg-list");
  const draw = () => {
    const q = query.toLowerCase();
    const shown = items.filter((i) => (filter === "all" || i.labels.includes(filter))
      && (!q || `${i.subject} ${i.sender} ${i.course_code} ${i.snippet}`.toLowerCase().includes(q)));
    list.innerHTML = shown.map((i) => `
      <button class="msg" data-open="${esc(i.record_id)}">
        <span>${i.urgent ? `<span class="urgent" title="Something is due within two days"></span>` : ""}</span>
        <span style="min-width:0">
          <span class="subject">${esc(i.subject || "(no subject)")}</span>
          <span class="meta">${senderLine(i)}</span>
          <span class="snippet">${esc(i.snippet)}</span>
          <span class="labels">${labelChips(i.labels)}${i.draft_status === "reviewed" ? `<span class="chip green">Reply ready</span>` : ""}</span>
        </span>
        <span class="when">${esc(fmtDateTime(i.received_at))}</span>
      </button>`).join("") || `<div class="empty">${items.length ? "Nothing matches." : "No messages yet. Add some with “Add messages”."}</div>`;
  };
  draw();

  root.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.filter;
    root.querySelectorAll("[data-filter]").forEach((x) => x.classList.toggle("active", x === b));
    draw();
  }));
  root.querySelector("#search").addEventListener("input", (e) => { query = e.target.value; draw(); });
  list.addEventListener("click", (e) => {
    const row = e.target.closest("[data-open]");
    if (row) openSource(row.dataset.open, ctx);
  });
  root.querySelector("[data-add]").addEventListener("click", () => addDialog("email", ctx));
  root.querySelector("[data-sync]").addEventListener("click", () => syncDialog("email", ctx));
  if (params.get("open")) openSource(params.get("open"), ctx);
}
