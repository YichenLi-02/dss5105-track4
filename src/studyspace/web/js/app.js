// Shell: routing, workspace status, navigation counts, theme. Each page module exports render(root, ctx).
import { api } from "./api.js";
import { confirmDialog, esc, fmtDateTime, initials, showError, toast } from "./util.js";
import * as sources from "./pages/sources.js";
import * as inbox from "./pages/inbox.js";
import * as review from "./pages/review.js";
import * as plan from "./pages/plan.js";
import * as replies from "./pages/replies.js";
import * as meetings from "./pages/meetings.js";
import * as privacy from "./pages/privacy.js";
import * as settings from "./pages/settings.js";

const PAGES = {
  sources: { mod: sources, title: "Sources", nav: "sources" },
  inbox: { mod: inbox, title: "All messages", nav: "sources" },
  review: { mod: review, title: "Review tasks" },
  plan: { mod: plan, title: "Study plan" },
  replies: { mod: replies, title: "Replies" },
  meetings: { mod: meetings, title: "Find a meeting time" },
  privacy: { mod: privacy, title: "Privacy & data" },
  settings: { mod: settings, title: "Settings" },
};

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
    const name = ws.profile?.name || "Student";
    document.getElementById("avatar").textContent = initials(name);
    document.getElementById("ws-name").textContent = name === "Student" ? "Your workspace" : name;
    document.getElementById("ws-sub").textContent = ws.demo_clock ? "Demo · fictional data" : "Student planner";
    const bar = document.getElementById("demo-bar");
    bar.hidden = !ws.demo_clock;
    document.getElementById("demo-text").textContent = `Fictional data · clock fixed at ${fmtDateTime(ws.now)}`;
    const chip = document.getElementById("mode-chip");
    if (ws.llm_provider === "offline") {
      chip.className = "chip green";
      chip.innerHTML = `<span class="dot"></span>Offline mode`;
      chip.title = "Extraction runs on this computer. No message is sent anywhere.";
    } else {
      chip.className = "chip amber";
      chip.innerHTML = `<span class="dot"></span>Model: ${esc(ws.llm_provider)}`;
      chip.title = "Cleaned, redacted text is sent to this provider. See Privacy & data.";
    }
    setCount("count-sources", inboxItems.filter((i) => i.urgent).length || "");
    setCount("count-review", ws.candidates_pending || "");
    setCount("count-plan", ws.adopted_plan ? "" : ws.tasks ? "!" : "");
    setCount("count-replies", inboxItems.filter((i) => i.labels.includes("reply") && i.draft_status !== "reviewed").length || "");
  } catch (err) {
    showError(err);
  }
}

function setCount(id, value) {
  const el = document.getElementById(id);
  el.textContent = value;
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [page, query] = raw.split("?");
  return { page: PAGES[page] ? page : "sources", params: new URLSearchParams(query || "") };
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
  root.innerHTML = `<div class="loading"><span class="spinner"></span></div>`;
  try {
    await PAGES[page].mod.render(root, ctx, params);
  } catch (err) {
    root.innerHTML = `<div class="card empty"><strong>Could not load this page</strong>${esc(err.message)}</div>`;
    showError(err);
  }
  loadShell();
}

// ---- global actions -------------------------------------------------------------------------
export async function loadDemo(button) {
  if (ctx.workspace?.sources && !(await confirmDialog("Load the demo student?", "This replaces everything in this workspace with fictional data for one student (clock: Monday 12 Oct 2026, 08:00).", "Load demo"))) return;
  if (button) button.disabled = true;
  try {
    const r = await api.post("/api/demo/load");
    toast(`Loaded ${r.import.added} emails and files, the timetable and free hours. ${r.candidates} tasks found.`);
    await loadShell();
    ctx.go("sources");
    route();
  } catch (err) { showError(err); } finally { if (button) button.disabled = false; }
}

async function resetWorkspace() {
  if (!(await confirmDialog("Clear this workspace?", "All messages, tasks, plans and settings stored for this workspace on this computer are deleted. This cannot be undone.", "Delete everything", true))) return;
  try {
    await api.post("/api/workspace/reset");
    toast("Workspace cleared.");
    await loadShell();
    ctx.go("sources");
    route();
  } catch (err) { showError(err); }
}

document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-global]");
  if (!g) return;
  if (g.dataset.global === "load-demo") loadDemo(g);
  if (g.dataset.global === "reset") resetWorkspace();
});

document.getElementById("menu-toggle").addEventListener("click", () => document.body.classList.toggle("menu-open"));

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

window.addEventListener("hashchange", route);
route();
