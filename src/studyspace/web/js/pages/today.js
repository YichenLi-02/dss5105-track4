// Today: the student's daily home. What's next, what needs them, what's due, how the week is loaded.
import { api } from "../api.js";
import { EFFORT_CHOICES, cantMakeIt, confirmCandidate, recordDone } from "../actions.js";
import { openFocus } from "../focus.js";
import { icon } from "../icons.js";
import { addDialog } from "../sources-common.js";
import {
  courseTag, dueLabel, esc, fmtDayLong, fmtMinutes, fmtRange, fmtTime, fromNow, minutesBetween, sgParts, showError, toast, urgency,
} from "../util.js";

export async function render(root, ctx) {
  const t = await api.get("/api/today");
  const now = t.now;
  if (t.empty) return renderEmpty(root, ctx, t);

  const sessionsToday = t.agenda.filter((a) => a.type === "session" && !a.done);
  const deadlinesToday = t.agenda.filter((a) => a.type === "deadline").length + t.due_soon.filter((d) => d.state === "to_check" && d.due_at && d.due_at.slice(0, 10) === now.slice(0, 10)).length;
  const summary = [
    sessionsToday.length ? `${sessionsToday.length} study session${sessionsToday.length === 1 ? "" : "s"} today` : "No study sessions today",
    deadlinesToday ? `${deadlinesToday} deadline${deadlinesToday === 1 ? "" : "s"} today` : "",
    t.attention.length ? `${t.attention.length} thing${t.attention.length === 1 ? "" : "s"} need you` : "nothing needs you right now",
  ].filter(Boolean).join(" · ");

  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">${esc([t.term, fmtDayLong(now)].filter(Boolean).join(" · "))}</p>
        <h1>${esc(t.greeting)}${t.name ? `, ${esc(t.name)}` : ""}</h1>
        <p class="lede">${esc(summary)}.</p>
      </div>
    </div>
    <div class="grid today-grid">
      <div class="stack">
        ${nextUp(t)}
        ${needsYou(t)}
        ${timeline(t)}
      </div>
      <aside class="stack">
        ${dueSoon(t)}
        ${weekChart(t)}
        ${agentCard(t)}
      </aside>
    </div>`;

  bind(root, ctx, t);
}

// ---- next up ---------------------------------------------------------------------------------
function nextUp(t) {
  const s = t.next_session;
  if (s) {
    const isNow = s.state === "now";
    const mins = minutesBetween(s.start, s.end);
    return `
    <section class="card next-card ${isNow ? "live" : ""}">
      <div class="next-main">
        <p class="next-label">${isNow ? `<span class="live-dot"></span>Happening now` : `Next up · ${esc(fromNow(s.start, t.now))}`}</p>
        <h2>${esc(s.title)}</h2>
        <p class="next-meta">${courseTag(s.course_code)}<span>${esc(fmtRange(s.start, s.end))}</span><span>${esc(fmtMinutes(mins))}</span>${s.locked ? `<span class="chip">${icon("lock", 12)} Locked</span>` : ""}</p>
      </div>
      <div class="next-actions">
        <button class="btn primary" data-focus>${icon("play", 15)} Start focus</button>
        <button class="btn" data-done-next>Done</button>
        <button class="btn ghost" data-cant>Can't make it</button>
      </div>
    </section>`;
  }
  if (!t.has_plan && t.counts.open_tasks) {
    return `<section class="card next-card empty-next"><div class="next-main"><p class="next-label">No plan yet</p>
      <h2>${t.counts.open_tasks} confirmed task${t.counts.open_tasks === 1 ? " is" : "s are"} waiting for time</h2>
      <p class="next-meta">Studyspace fits them into your free hours, never past a deadline.</p></div>
      <div class="next-actions"><a class="btn primary" href="#/plan">Make my plan ${icon("arrow", 14)}</a></div></section>`;
  }
  if (t.counts.to_check) {
    return `<section class="card next-card empty-next"><div class="next-main"><p class="next-label">Start here</p>
      <h2>${t.counts.to_check} task${t.counts.to_check === 1 ? "" : "s"} found in your messages</h2>
      <p class="next-meta">Check their deadlines and effort, then Studyspace plans your week.</p></div>
      <div class="next-actions"><a class="btn primary" href="#/tasks">Check tasks ${icon("arrow", 14)}</a></div></section>`;
  }
  return `<section class="card next-card empty-next"><div class="next-main"><p class="next-label">All clear</p>
    <h2>Nothing planned right now</h2><p class="next-meta">Enjoy the free time, or add something new.</p></div></section>`;
}

// ---- needs you -------------------------------------------------------------------------------
function needsYou(t) {
  if (!t.attention.length) {
    return `<section class="card"><div class="card-head"><h2>Needs you</h2></div><div class="calm">${icon("check", 22)}<span>You're on top of everything. Studyspace will tell you when something new needs a decision.</span></div></section>`;
  }
  // decisions are shown inline two at a time; the rest wait on the Tasks page, so the list stays short
  const picks = t.attention.filter((a) => a.kind === "choose_time");
  const rows = t.attention.map((a, i) => {
    if (a.kind !== "choose_time") return attnItem(a, i, t);
    const k = picks.indexOf(a);
    if (k < 2) return attnItem(a, i, t);
    if (k === 2) return `<div class="attn"><span class="attn-icon amber">${icon("clock", 16)}</span><div class="attn-text"><b>${picks.length - 2} more deadline${picks.length - 2 === 1 ? "" : "s"} to pick</b><span>${esc(picks.slice(2).map((p) => p.title).join(", "))}</span></div><div class="attn-actions"><a class="btn small" href="#/tasks?section=decide">Pick them</a></div></div>`;
    return "";
  }).join("");
  return `
  <section class="card">
    <div class="card-head"><h2>Needs you</h2><span class="chip amber">${t.attention.length}</span></div>
    <div class="attn-list">${rows}</div>
  </section>`;
}

function attnItem(a, i, t) {
  const row = (tone, ic, title, detail, actions, extra = "") => `
    <div class="attn" data-attn="${i}">
      <span class="attn-icon ${tone}">${icon(ic, 16)}</span>
      <div class="attn-text"><b>${title}</b>${detail ? `<span>${detail}</span>` : ""}${extra}</div>
      <div class="attn-actions">${actions}</div>
    </div>`;
  switch (a.kind) {
    case "choose_time": {
      const opts = a.options.length
        ? a.options.map((o) => ({ value: o, label: `${dueLabel(o, t.now)}${o.endsWith("T00:00:00+08:00") ? " · start of day" : o.includes("T23:59") ? " · end of day" : ""}` }))
        : ["09:00", "12:00", "17:00", "23:59"].map((h) => ({ value: `${a.due_date}T${h}:00+08:00`, label: h }));
      const why = a.flags.includes("MIDNIGHT_AMBIGUITY") ? "“Midnight” can mean the start or the end of the day." : a.options.length ? "Linked to an exam in the same message." : `The message says ${esc(a.due_text || a.due_date)} but no time.`;
      return row("amber", "clock", `Pick the deadline for ${esc(a.title)}`, `${courseTag(a.course_code)} ${esc(why)}`, "", `
        <div class="pick" data-pick-group>
          <div class="seg">${opts.map((o) => `<button class="seg-btn" data-value="${esc(o.value)}">${esc(o.label)}</button>`).join("")}</div>
          <div class="seg small">${[...new Set([...EFFORT_CHOICES.slice(0, 6), a.suggested_minutes])].sort((x, y) => x - y).map((m) => `<button class="seg-btn ${m === a.suggested_minutes ? "on suggested" : ""}" data-minutes="${m}">${fmtMinutes(m)}</button>`).join("")}</div>
          <button class="btn small primary" data-confirm-pick>Confirm</button>
        </div>`);
    }
    case "confirm_ready":
      return row("purple", "check", `${a.count} task${a.count === 1 ? " is" : "s are"} ready to confirm`, "Dates and times are clear. Add how long each takes.", `<a class="btn small" href="#/tasks">Review</a>`);
    case "past_due":
      return row("red", "flag", `${a.count} deadline${a.count === 1 ? " has" : "s have"} already passed`, "Mark them done or set them aside.", `<a class="btn small" href="#/tasks?section=past">Look</a>`);
    case "no_date":
      return row("grey", "calendar", `${a.count} task${a.count === 1 ? " has" : "s have"} no deadline`, "Add a date so they can be planned.", `<a class="btn small" href="#/tasks?section=undated">Add dates</a>`);
    case "reply":
      return row("blue", "reply", `${esc(senderShort(a.sender))} is waiting for a reply`, esc(a.subject || ""), `<a class="btn small" href="#/replies?open=${encodeURIComponent(a.record_id)}">Draft reply</a>`);
    case "replan":
      return row("amber", "sync", "Your plan may no longer fit", esc(a.reasons.slice(0, 2).join("; ")), `<a class="btn small primary" href="#/plan?replan=1">Update plan</a>`);
    case "no_plan":
      return row("purple", "calendar", `${a.count} confirmed task${a.count === 1 ? "" : "s"} not planned yet`, "One click fits them into your free hours.", `<a class="btn small primary" href="#/plan">Make plan</a>`);
    case "missed_session":
      return row("grey", "clock", `Did you do ${esc(a.title)}?`, `Planned ${esc(fmtRange(a.start, a.end))}`, `<button class="btn small" data-missed-yes>Yes, done</button><button class="btn small ghost" data-missed-no>No</button>`);
    default:
      return "";
  }
}

function senderShort(s) { return (s || "Someone").replace(/<.*>/, "").replace(/\(.*?\)/, "").trim(); }

// ---- today's timeline -------------------------------------------------------------------------
function timeline(t) {
  const items = t.agenda;
  if (!items.length) return `<section class="card"><div class="card-head"><h2>Today</h2></div><div class="calm">${icon("sun", 22)}<span>No classes, sessions or deadlines today.</span></div></section>`;
  let nowShown = false;
  const rows = items.map((a) => {
    let marker = "";
    if (!nowShown && a.start > t.now) { nowShown = true; marker = `<li class="now-line"><span>${esc(fmtTime(t.now))}</span></li>`; }
    const label = { class: "Class", commitment: "Busy", session: "Study", event: "Exam / event", deadline: "Deadline" }[a.type];
    const time = a.type === "deadline" ? fmtTime(a.start) : fmtRange(a.start, a.end);
    return `${marker}<li class="ag ag-${a.type} ${a.done ? "done" : ""}">
      <span class="ag-time">${esc(time)}</span>
      <span class="ag-bar"></span>
      <span class="ag-body"><b>${esc(a.title)}</b><span>${a.course_code ? courseTag(a.course_code) : ""}${esc(label)}${a.done ? " · done" : a.locked ? " · locked" : ""}</span></span>
    </li>`;
  }).join("");
  return `<section class="card"><div class="card-head"><h2>Today</h2><a class="btn small ghost" href="#/plan">Open plan</a></div>
    <ol class="agenda">${rows}${nowShown ? "" : `<li class="now-line"><span>${esc(fmtTime(t.now))}</span></li>`}</ol></section>`;
}

// ---- due soon ---------------------------------------------------------------------------------
function dueSoon(t) {
  if (!t.due_soon.length) return `<section class="card"><div class="card-head"><h2>Due in 7 days</h2></div><div class="calm small">${icon("check", 18)}<span>Nothing due this week.</span></div></section>`;
  return `<section class="card"><div class="card-head"><h2>Due in 7 days</h2><span class="tiny muted">${t.due_soon.length}</span></div>
    <div class="due-list">${t.due_soon.map((d) => {
      const when = d.due_at || `${d.due_date}T23:59:00+08:00`;
      const covered = d.state === "confirmed" ? Math.min(100, Math.round(((d.planned || 0) / Math.max(1, d.remaining)) * 100)) : null;
      return `<a class="due" href="${d.state === "confirmed" ? "#/plan" : `#/tasks?focus=${encodeURIComponent(d.candidate_id)}`}">
        <span class="due-top"><span class="due-title">${esc(d.title)}</span><span class="chip ${urgency(when, t.now)}">${esc(d.due_at ? fromNow(d.due_at, t.now) : "day only")}</span></span>
        <span class="due-meta">${courseTag(d.course_code)}<span>${esc(d.due_at ? dueLabel(d.due_at, t.now) : `${sgParts(when).weekday}, time to choose`)}</span>
        ${d.state === "to_check" ? `<span class="chip outline">to check</span>` : `<span class="meter" title="${fmtMinutes(d.planned || 0)} planned of ${fmtMinutes(d.remaining)} left"><span style="width:${covered}%"></span></span>`}</span>
      </a>`;
    }).join("")}</div></section>`;
}

// ---- week load (single-series column chart with the daily limit as a reference line) ----------
function weekChart(t) {
  const W = 280, H = 132, top = 18, base = 104, colW = 22;
  const limit = t.week[0]?.limit || 180;
  const maxV = Math.max(limit, ...t.week.map((d) => d.planned_minutes + d.done_minutes)) || 1;
  const y = (v) => base - (v / maxV) * (base - top);
  const step = W / 7;
  const todayIso = t.now.slice(0, 10);
  const total = t.week.reduce((n, d) => n + d.planned_minutes + d.done_minutes, 0);
  const cols = t.week.map((d, i) => {
    const v = d.planned_minutes + d.done_minutes;
    const x = i * step + (step - colW) / 2;
    const h = base - y(v);
    const p = sgParts(`${d.date}T12:00:00+08:00`);
    const isToday = d.date === todayIso;
    const past = d.date < todayIso;
    const r = Math.min(4, h);
    const path = v > 0 ? `M${x},${base} V${base - h + r} Q${x},${base - h} ${x + r},${base - h} H${x + colW - r} Q${x + colW},${base - h} ${x + colW},${base - h + r} V${base} Z` : "";
    const tip = `${p.weekday} ${p.d}: ${fmtMinutes(v) || "0 min"} study${d.done_minutes ? ` (${fmtMinutes(d.done_minutes)} done)` : ""} · ${fmtMinutes(d.free_minutes) || "no"} free`;
    return `<g class="wk-col ${isToday ? "today" : ""} ${past ? "past" : ""}" tabindex="0" aria-label="${esc(tip)}">
      <rect x="${i * step}" y="0" width="${step}" height="${H}" class="wk-hit"><title>${esc(tip)}</title></rect>
      ${path ? `<path d="${path}" class="wk-bar"/>` : `<rect x="${x}" y="${base - 1}" width="${colW}" height="1" class="wk-zero"/>`}
      ${isToday && v ? `<text x="${x + colW / 2}" y="${base - h - 5}" class="wk-val">${esc(fmtMinutes(v).replace(" min", "m"))}</text>` : ""}
      <text x="${x + colW / 2}" y="${base + 16}" class="wk-day">${esc(p.weekday.slice(0, 2))}</text>
    </g>`;
  }).join("");
  if (!total) {
    const free = t.week.reduce((n, d) => n + d.free_minutes, 0);
    return `<section class="card"><div class="card-head"><h2>This week</h2></div><div class="calm small">${icon("calendar", 18)}<span>No study planned yet. You have ${esc(fmtMinutes(free) || "no")} of free hours this week. <a href="#/plan">Make a plan</a></span></div></section>`;
  }
  return `<section class="card"><div class="card-head"><h2>This week</h2><span class="tiny muted">${esc(fmtMinutes(total))} planned</span></div>
    <div class="card-body" style="padding-top:12px">
      <svg viewBox="0 0 ${W} ${H}" class="wk-chart" role="img" aria-label="Study time planned per day this week">
        <line x1="0" x2="${W}" y1="${base}" y2="${base}" class="wk-axis"/>
        <line x1="0" x2="${W}" y1="${y(limit)}" y2="${y(limit)}" class="wk-limit"/>
        <text x="${W}" y="${y(limit) - 4}" class="wk-limit-label" text-anchor="end">${esc(fmtMinutes(limit))} daily limit</text>
        ${cols}
      </svg>
      <table class="sr-only"><caption>Study time per day</caption><tr><th>Day</th><th>Planned or done</th><th>Free</th></tr>
        ${t.week.map((d) => `<tr><td>${esc(d.date)}</td><td>${esc(fmtMinutes(d.planned_minutes + d.done_minutes) || "0")}</td><td>${esc(fmtMinutes(d.free_minutes) || "0")}</td></tr>`).join("")}</table>
    </div></section>`;
}

function agentCard(t) {
  if (!t.activity.length) return "";
  return `<section class="card"><div class="card-head"><h2>What your agent did</h2><a class="btn small ghost" href="#/sources">Sources</a></div>
    <ol class="timeline compact">${t.activity.map((x) => `<li><span class="t-dot ${x.kind === "extract" ? "accent" : x.kind === "plan" ? "green" : "grey"}"></span><span class="t-text">${esc(x.label)}</span></li>`).join("")}</ol></section>`;
}

// ---- empty workspace ----------------------------------------------------------------------------
function renderEmpty(root, ctx, t) {
  root.innerHTML = `
    <div class="page-head"><div><p class="eyebrow">${esc(t.term || "Welcome")}</p><h1>Welcome to Studyspace</h1>
      <p class="lede">Three quick steps and your agent can start reading your course messages and planning your week.</p></div></div>
    <section class="card onboard">
      ${[["calendar", "Add your timetable", "NUSMods › Download › iCal (.ics). Studyspace never plans over your classes.", "timetable"],
         ["mail", "Add course emails", "Save emails from Outlook or Gmail as .eml, or paste a message.", "email"],
         ["file", "Add course files", "Assignment briefs and slides (PDF). Deadlines inside are found too.", "files"]].map(([ic, title, text, kind], i) => `
        <div class="onboard-step"><span class="onboard-n">${i + 1}</span><span class="attn-icon purple">${icon(ic, 16)}</span>
          <div class="attn-text"><b>${title}</b><span>${text}</span></div><button class="btn small" data-onboard="${kind}">Add</button></div>`).join("")}
      <div class="onboard-foot"><span class="muted small">Just looking around?</span><button class="btn primary" data-global="load-demo">Try with a demo student</button></div>
    </section>`;
  root.querySelectorAll("[data-onboard]").forEach((b) => b.addEventListener("click", () => addDialog(b.dataset.onboard, ctx)));
}

// ---- events -------------------------------------------------------------------------------------
function bind(root, ctx, t) {
  const s = t.next_session;
  if (s) {
    const block = { ...s };
    const task = { title: s.title, course_code: s.course_code };
    root.querySelector("[data-focus]")?.addEventListener("click", async () => {
      const tasks = await api.get("/api/tasks");  // the timer's "done" needs the real work left
      openFocus(ctx, block, tasks.find((x) => x.task_id === s.task_id) || task);
    });
    root.querySelector("[data-done-next]")?.addEventListener("click", async () => {
      const tasks = await api.get("/api/tasks");
      recordDone(ctx, block, tasks.find((x) => x.task_id === s.task_id));
    });
    root.querySelector("[data-cant]")?.addEventListener("click", () => cantMakeIt(ctx, block));
  }
  root.querySelectorAll("[data-attn]").forEach((el) => {
    const a = t.attention[+el.dataset.attn];
    el.querySelectorAll(".seg").forEach((seg) => seg.addEventListener("click", (e) => {
      const b = e.target.closest(".seg-btn");
      if (!b) return;
      seg.querySelectorAll(".seg-btn").forEach((x) => x.classList.toggle("on", x === b));
    }));
    el.querySelector("[data-confirm-pick]")?.addEventListener("click", async () => {
      const due = el.querySelector("[data-value].on")?.dataset.value;
      const minutes = +(el.querySelector("[data-minutes].on")?.dataset.minutes || 0);
      if (!due) return toast("Pick a time first.", "error");
      if (!minutes) return toast("Pick how long it takes.", "error");
      try { await confirmCandidate(ctx, { candidate_id: a.candidate_id, title: a.title }, { due_at: due, minutes }); } catch (err) { showError(err); }
    });
    el.querySelector("[data-missed-yes]")?.addEventListener("click", async () => {
      const tasks = await api.get("/api/tasks");
      recordDone(ctx, a, tasks.find((x) => x.task_id === a.task_id));
    });
    el.querySelector("[data-missed-no]")?.addEventListener("click", () => ctx.go("plan", "replan=1"));
  });
}
