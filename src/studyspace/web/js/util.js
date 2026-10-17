// Formatting and small DOM helpers. All times are shown in Singapore time.

export const TZ = "Asia/Singapore";

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const fmt = (opts) => new Intl.DateTimeFormat("en-SG", { timeZone: TZ, ...opts });
const F = {
  day: fmt({ weekday: "short", day: "numeric", month: "short" }),
  dayLong: fmt({ weekday: "long", day: "numeric", month: "long" }),
  time: fmt({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" }),
  date: fmt({ day: "numeric", month: "short" }),
  parts: fmt({ year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short" }),
};

export const fmtDay = (iso) => (iso ? F.day.format(new Date(iso)) : "");
export const fmtDayLong = (iso) => (iso ? F.dayLong.format(new Date(iso)) : "");
export const fmtTime = (iso) => (iso ? F.time.format(new Date(iso)) : "");
export const fmtDate = (iso) => (iso ? F.date.format(new Date(iso)) : "");
export const fmtDateTime = (iso) => (iso ? `${fmtDay(iso)}, ${fmtTime(iso)}` : "");
export function fmtRange(start, end) { return `${fmtTime(start)} – ${fmtTime(end)}`; }

export function sgParts(iso) {
  const p = Object.fromEntries(F.parts.formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return { y: +p.year, m: +p.month, d: +p.day, h: +p.hour, min: +p.minute, weekday: p.weekday };
}

/** "2026-10-12" for the Singapore calendar day of an instant. */
export function sgDate(iso) {
  const p = sgParts(iso);
  return `${p.y}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
}

/** Value for <input type="datetime-local"> in Singapore time. */
export function toLocalInput(iso) {
  if (!iso) return "";
  const p = sgParts(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${p.y}-${pad(p.m)}-${pad(p.d)}T${pad(p.h)}:${pad(p.min)}`;
}

/** ISO string with +08:00 from a datetime-local value. */
export function fromLocalInput(value) {
  if (!value) return null;
  return `${value.length === 16 ? value + ":00" : value}+08:00`;
}

export function addDays(dateStr, n) {
  const d = new Date(`${dateStr}T12:00:00+08:00`);
  d.setUTCDate(d.getUTCDate() + n);
  return sgDate(d.toISOString());
}

export function mondayOf(dateStr) {
  const d = new Date(`${dateStr}T12:00:00+08:00`);
  const wd = (d.getUTCDay() + 6) % 7;
  return addDays(dateStr, -wd);
}

export const hours = (minutes) => {
  const h = minutes / 60;
  return Number.isInteger(h) ? `${h}` : h.toFixed(h < 10 ? 2 : 1).replace(/0$/, "");
};

export function minutesBetween(a, b) { return Math.round((new Date(b) - new Date(a)) / 60000); }

export function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((s) => s[0].toUpperCase()).join("");
}

export function senderName(sender) {
  if (!sender) return "Unknown sender";
  const m = sender.match(/^\s*"?([^"<]+?)"?\s*<([^>]+)>/);
  return m ? m[1].trim() : sender;
}

// ---- feedback -------------------------------------------------------------------------------
let toastTimer;
export function toast(message, kind = "info") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `show ${kind === "error" ? "error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ""), kind === "error" ? 5200 : 3200);
}

export function showError(err) {
  console.error(err);
  toast(err?.message || String(err), "error");
}

/** Open a modal. `render(root)` fills it; resolves with the value passed to close(). */
export function modal(title, bodyHtml, { actions = [], wide = false } = {}) {
  const dlg = document.getElementById("modal");
  dlg.style.width = wide ? "min(820px, calc(100vw - 32px))" : "";
  dlg.innerHTML = `
    <div class="modal-head"><h3 id="modal-title">${esc(title)}</h3><button class="btn small ghost" data-close aria-label="Close">✕</button></div>
    <div class="modal-body">${bodyHtml}</div>
    ${actions.length ? `<div class="modal-foot">${actions.map((a, i) => `<button class="btn ${a.primary ? "primary" : ""} ${a.danger ? "danger" : ""}" data-action-index="${i}">${esc(a.label)}</button>`).join("")}</div>` : ""}`;
  return new Promise((resolve) => {
    const close = (value) => { dlg.close(); resolve(value); };
    dlg.onclick = async (e) => {
      if (e.target === dlg || e.target.closest("[data-close]")) return close(null);
      const btn = e.target.closest("[data-action-index]");
      if (!btn) return;
      const action = actions[+btn.dataset.actionIndex];
      if (action.onClick) {
        btn.disabled = true;
        try {
          const result = await action.onClick(dlg);
          if (result !== false) close(result ?? action.value ?? true);
        } catch (err) {
          showError(err);
        } finally {
          btn.disabled = false;
        }
      } else {
        close(action.value ?? true);
      }
    };
    dlg.oncancel = (e) => { e.preventDefault(); close(null); };
    dlg.showModal();
    const first = dlg.querySelector("input, textarea, select");
    if (first) first.focus();
  });
}

export async function confirmDialog(title, message, label = "Confirm", danger = false) {
  return modal(title, `<p class="muted" style="margin:0">${esc(message)}</p>`, {
    actions: [{ label: "Cancel", value: false }, { label, primary: !danger, danger, value: true }],
  });
}

export async function busy(button, fn) {
  const label = button ? button.innerHTML : null;
  if (button) { button.disabled = true; button.innerHTML = `<span class="spinner"></span>`; }
  try { return await fn(); }
  finally { if (button) { button.disabled = false; button.innerHTML = label; } }
}

// ---- labels ---------------------------------------------------------------------------------
export const FLAG_TEXT = {
  NEEDS_CONFIRM: ["Check date", "amber", "The date was worked out from the wording (e.g. 'this Friday') or the time is missing."],
  MISSING_DUE_AT: ["No deadline", "red", "The message gives no deadline. Add one before it can be planned."],
  MIDNIGHT_AMBIGUITY: ["Midnight?", "amber", "'12 midnight' can mean the start or the end of the day. Choose one."],
  DATE_CHANGED: ["Date changed", "blue", "A later message moved this deadline. The history shows the earlier dates."],
};

export const WARNING_TEXT = {
  INSUFFICIENT_TIME: "Not enough time",
  LOW_BUFFER: "Less than a day to spare",
  PAST_DEADLINE: "Deadline has passed",
  MISSING_DUE_AT: "No deadline yet",
  UNCONFIRMED_TASK: "Not confirmed",
  LOCK_CONFLICT: "Locked session clashes",
  DEADLINE_CLUSTER: "Deadlines bunch up",
};

export const LABEL_TEXT = {
  task: ["Task", ""],
  reply: ["Reply needed", "amber"],
  event: ["Event", "blue"],
  info: ["Info", "grey"],
  newsletter: ["Newsletter", "outline"],
};

export function flagChips(flags = []) {
  return flags.map((f) => {
    const [text, color, tip] = FLAG_TEXT[f] || [f, "grey", f];
    return `<span class="chip ${color}" title="${esc(tip)}">${esc(text)}</span>`;
  }).join(" ");
}

export function courseColorClass(id, palette = 6) {
  let h = 0;
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `c${(h % palette) + 1}`;
}
