// Focus timer: a calm countdown for one planned session. Real time, kept only in this tab.
import { recordDone } from "./actions.js";
import { icon } from "./icons.js";
import { courseTag, esc, fmtRange, minutesBetween } from "./util.js";

let timer = null;

export function openFocus(ctx, block, task) {
  const total = Math.max(5, minutesBetween(block.start, block.end)) * 60;
  let left = total;
  let running = true;
  const dlg = document.getElementById("modal");
  dlg.style.width = "min(440px, calc(100vw - 32px))";
  dlg.innerHTML = `
    <div class="focus">
      <button class="icon-btn focus-close" data-close aria-label="Close">${icon("x", 16)}</button>
      <p class="eyebrow" style="margin:0">Focus session</p>
      <h3>${esc(task?.title || block.title || "Study")}</h3>
      <p class="small muted" style="margin:0">${courseTag(task?.course_code || block.course_code)} planned ${esc(fmtRange(block.start, block.end))}</p>
      <div class="ring">
        <svg viewBox="0 0 120 120" aria-hidden="true"><circle cx="60" cy="60" r="52" class="ring-track"/><circle cx="60" cy="60" r="52" class="ring-fill" id="ring-fill"/></svg>
        <div class="ring-time" id="ring-time" aria-live="off">--:--</div>
      </div>
      <div class="row" style="justify-content:center">
        <button class="btn" id="f-toggle">${icon("pause", 15)} Pause</button>
        <button class="btn primary" id="f-done">I'm done</button>
      </div>
      <p class="tiny muted" style="margin:0">Phone face down. One task. Studyspace counts the session when you finish.</p>
    </div>`;
  const fill = dlg.querySelector("#ring-fill");
  const C = 2 * Math.PI * 52;
  fill.style.strokeDasharray = `${C}`;
  const draw = () => {
    const m = Math.floor(left / 60), s = left % 60;
    dlg.querySelector("#ring-time").textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    fill.style.strokeDashoffset = `${C * (1 - left / total)}`;
    document.title = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")} · ${task?.title || "Focus"}`;
  };
  const stop = () => { clearInterval(timer); timer = null; document.title = "Studyspace"; };
  clearInterval(timer);
  timer = setInterval(() => {
    if (!running) return;
    left = Math.max(0, left - 1);
    draw();
    if (left === 0) {
      stop();
      dlg.querySelector("#ring-time").textContent = "Done";
      dlg.querySelector("#f-toggle").hidden = true;
    }
  }, 1000);
  draw();
  dlg.querySelector("#f-toggle").onclick = (e) => {
    running = !running;
    e.currentTarget.innerHTML = running ? `${icon("pause", 15)} Pause` : `${icon("play", 15)} Resume`;
  };
  dlg.querySelector("#f-done").onclick = () => { stop(); dlg.close(); recordDone(ctx, block, task); };
  dlg.onclick = (e) => { if (e.target.closest("[data-close]")) { stop(); dlg.close(); } };
  dlg.oncancel = (e) => { e.preventDefault(); stop(); dlg.close(); };
  dlg.showModal();
}
