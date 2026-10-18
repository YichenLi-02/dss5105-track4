// Shell: routing, workspace status, navigation counts, quick add, drop-anywhere, theme.
// Each page module exports render(root, ctx, params).
import { api } from "./api.js";
import { hydrateIcons } from "./icons.js";
import { addDialog, uploadFiles } from "./sources-common.js";
import { confirmDialog, esc, fmtDateTime, initials, menu, setCourses, showError, toast } from "./util.js";
import * as today from "./pages/today.js";
import * as sources from "./pages/sources.js";
import * as inbox from "./pages/inbox.js";
import * as tasks from "./pages/tasks.js";
import * as plan from "./pages/plan.js";
import * as replies from "./pages/replies.js";
import * as meetings from "./pages/meetings.js";
import * as privacy from "./pages/privacy.js";
import * as settings from "./pages/settings.js";

const PAGES = {
  today: { mod: today, title: "Today" },
  sources: { mod: sources, title: "Sources" },
  inbox: { mod: inbox, title: "All messages", nav: "sources" },
  tasks: { mod: tasks, title: "Tasks" },
  plan: { mod: plan, title: "Study plan" },
  replies: { mod: replies, title: "Replies" },
  meetings: { mod: meetings, title: "Meeting time" },
  privacy: { mod: privacy, title: "Privacy & data" },
  settings: { mod: settings, title: "Settings" },
};
const ALIASES = { review: "tasks" };  // old links keep working

export const ctx = {
  workspace: null,      // GET /api/workspace
  go(page, params = "") { location.hash = `#/${page}${params ? "?" + params : ""}`; },
  refresh: () => route(),
  refreshShell: () => loadShell(),
};

async function loadShell() {
  try {
    const [ws, inboxItems] = await Promise.all([api.get("/api/workspace"), api.get("/api/inbox")]);
    ctx.workspace = ws;
    setCourses(ws.courses);
    const name = ws.profile?.name || "Student";
    document.getElementById("avatar").textContent = initials(name);
    document.getElementById("ws-name").textContent = name === "Student" ? "Your workspace" : name;
    document.getElementById("ws-sub").textContent = [ws.term, ws.demo_clock ? "demo data" : ""].filter(Boolean).join(" · ") || "Student planner";
    const pill = document.getElementById("demo-pill");
    pill.hidden = !ws.demo_clock;
    document.getElementById("demo-text").textContent = `Demo · ${fmtDateTime(ws.now)}`;
    const chip = document.getElementById("mode-chip");
    if (ws.llm_provider === "offline") {
      chip.className = "chip green";
      chip.innerHTML = `<span class="dot"></span>Offline`;
      chip.title = "Extraction runs on this computer. No message is sent anywhere.";
    } else {
      chip.className = "chip amber";
      chip.innerHTML = `<span class="dot"></span>${esc(ws.llm_provider)}`;
      chip.title = "Cleaned, redacted text is sent to this provider. See Privacy & data.";
    }
    const replies = inboxItems.filter((i) => i.labels.includes("reply") && i.draft_status !== "reviewed").length;
    setCount("count-tasks", ws.candidates_pending || "");
    setCount("count-plan", ws.adopted_plan ? "" : ws.tasks ? "!" : "", true);
    setCount("count-replies", replies || "");
  } catch (err) {
    showError(err);
  }
}

function setCount(id, value, warn = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
  el.classList.toggle("warn", warn);
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  let [page, query] = raw.split("?");
  page = ALIASES[page] || page;
  return { page: PAGES[page] ? page : "today", params: new URLSearchParams(query || "") };
}

let routeToken = 0;
async function route() {
  const token = ++routeToken;
  const { page, params } = parseHash();
  document.body.classList.remove("menu-open");
  const navPage = PAGES[page].nav || page;
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === navPage));
  document.getElementById("breadcrumb").textContent = PAGES[page].title;
  document.title = `${PAGES[page].title} · Studyspace`;
  const root = document.getElementById("content");
  if (!ctx.workspace) await loadShell();
  if (token !== routeToken) return;
  if (!root.dataset.page || root.dataset.page !== page) {
    root.innerHTML = `<div class="skeleton"><div></div><div></div><div></div></div>`;
    window.scrollTo(0, 0);
  }
  root.dataset.page = page;
  try {
    await PAGES[page].mod.render(root, ctx, params);
  } catch (err) {
    root.innerHTML = `<div class="card empty"><strong>Could not load this page</strong>${esc(err.message)}</div>`;
    showError(err);
  }
  hydrateIcons(root);
  loadShell();
}

// ---- global actions -------------------------------------------------------------------------
export async function loadDemo(button) {
  if (ctx.workspace?.sources && !(await confirmDialog("Load the demo student?", "This replaces everything in this workspace with fictional data for one student (clock: Monday 12 Oct 2026, 08:00).", "Load demo"))) return;
  if (button) button.disabled = true;
  try {
    const r = await api.post("/api/demo/load");
    toast(`Loaded ${r.import.added} emails and files, a timetable and free hours. ${r.candidates} tasks found.`);
    await loadShell();
    ctx.go("today");
    route();
  } catch (err) { showError(err); } finally { if (button) button.disabled = false; }
}

async function resetWorkspace() {
  if (!(await confirmDialog("Clear this workspace?", "All messages, tasks, plans and settings stored for this workspace on this computer are deleted. This cannot be undone.", "Delete everything", true))) return;
  try {
    await api.post("/api/workspace/reset");
    toast("Workspace cleared.");
    await loadShell();
    ctx.go("today");
    route();
  } catch (err) { showError(err); }
}

document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-global]");
  if (!g) return;
  if (g.dataset.global === "load-demo") loadDemo(g);
  if (g.dataset.global === "reset") resetWorkspace();
});

document.getElementById("quick-add").addEventListener("click", (e) => menu(e.currentTarget, [
  { label: "Paste a message", hint: "Teams, WhatsApp, a forwarded email", icon: "paste", onClick: () => addDialog("email", ctx).then(() => {}) },
  { label: "Upload files", hint: ".eml, .csv, .ics, PDF", icon: "upload", onClick: () => addDialog("files", ctx) },
  { label: "Add a task myself", icon: "check", onClick: () => tasks.addTaskDialog(ctx) },
  { label: "Add a commitment", hint: "work, a meeting, a trip", icon: "calendar", onClick: () => addDialog("timetable", ctx) },
]));

document.getElementById("demo-pill").addEventListener("click", (e) => menu(e.currentTarget, [
  { label: "Reload the demo student", icon: "sync", onClick: () => loadDemo() },
  { label: "Clear this workspace", icon: "x", onClick: () => resetWorkspace() },
]));

document.getElementById("menu-toggle").addEventListener("click", () => document.body.classList.toggle("menu-open"));

// drop files anywhere to add them
const overlay = document.getElementById("drop-overlay");
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (!hasFiles(e) || document.getElementById("modal").open) return; dragDepth++; overlay.hidden = false; });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; overlay.hidden = true; } });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", async (e) => {
  if (!hasFiles(e) || document.getElementById("modal").open) return;
  e.preventDefault();
  dragDepth = 0;
  overlay.hidden = true;
  try { await uploadFiles(e.dataTransfer.files, ctx); } catch (err) { showError(err); }
});

// theme: follows the system unless the student picks one
function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem("studyspace.theme")); } catch { /* storage unavailable */ }
document.getElementById("theme-toggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("studyspace.theme", next); } catch { /* ignore */ }
});

hydrateIcons(document);
window.addEventListener("hashchange", route);
route();
