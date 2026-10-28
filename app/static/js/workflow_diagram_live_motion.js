/*
 * The live workflow chart's movement (workflow_diagram_live.js), on one shared clock: streaming arrows, breathing halos
 * and dots all advance together 10 times a second. Every change repaints the chart, so separate CSS animations (each
 * on its own timing) repainted it nearly every frame; one clock means one repaint per tick, however much moves. The
 * clock runs only while something moves and the window is in front and visible. (The cards breathe by a compositor-only
 * CSS animation, workflow.css: no repaint.)
 */

class WorkflowMotion {
  static TICK_MS = 100;
  static FLOW_PX_S = 30; // dash travel at speed 1 (the pattern repeats every 9.1px, style.css .wf-live-flow)
  static BREATHE_S = 1.4;
  static DOT_MS = 500;
  static MAX_DOTS = 60;

  constructor(dotLayer) {
    this.dotLayer = dotLayer;
    this.flows = new Set(); // streaming arrows
    this.dots = [];
    this.busy = false; // some node or card is breathing
    this.timer = null;
    this.t = 0;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.paused = false;
    for (const ev of ["focus", "blur"]) window.addEventListener(ev, () => this._sync());
    document.addEventListener("visibilitychange", () => this._sync());
  }

  /* An arrow streams (on) at `speed` (1 = 30px/s, faster for more tokens/s). */
  flow(flow, on, speed) {
    flow.speed = speed;
    flow.offset ??= 0;
    if (on) this.flows.add(flow);
    else this.flows.delete(flow);
    this._sync();
  }

  /* Whether any chart node is active (its halo breathes). */
  setBusy(busy) {
    this.busy = busy;
    this._sync();
  }

  /* A dot in the chat's colour runs once along the arrow: a round dash (core + faint glow) whose offset slides. */
  dot(flow, color) {
    if (this.reduced || this.paused || this.dots.length >= WorkflowMotion.MAX_DOTS) return;
    const g = this.dotLayer.append("g").attr("class", "wf-live-dot").attr("stroke", color);
    const d = flow.el.getAttribute("d");
    const gap = `0 ${flow.len + 20}`; // one dot; the rest of the dash pattern is past the arrow's end
    const parts = [9, 16].map((w) => g.append("path").attr("d", d).attr("stroke-width", w).attr("stroke-dasharray", gap).node());
    parts[1].setAttribute("opacity", 0.25);
    this.dots.push({ g, parts, len: flow.len, start: performance.now() });
    this._sync();
  }

  stop() {
    this.flows.clear();
    this.busy = false;
    this._sync();
  }

  _sync() {
    this.paused = !(document.visibilityState === "visible" && document.hasFocus());
    const moving = !this.reduced && !this.paused && (this.flows.size || this.dots.length || this.busy);
    if (moving && !this.timer) this.timer = setInterval(() => this._tick(), WorkflowMotion.TICK_MS);
    if (!moving && this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  _tick() {
    const dt = WorkflowMotion.TICK_MS / 1000;
    this.t += dt;
    for (const flow of this.flows) {
      flow.offset = (flow.offset - flow.speed * WorkflowMotion.FLOW_PX_S * dt) % 9.1;
      flow.el.style.strokeDashoffset = flow.offset.toFixed(2);
    }
    if (this.busy) {
      const wave = (1 + Math.sin((2 * Math.PI * this.t) / WorkflowMotion.BREATHE_S)) / 2; // 0..1
      for (const halo of document.querySelectorAll(".wf-node.wf-live-active .wf-live-halo")) halo.style.opacity = (0.18 + 0.37 * wave).toFixed(2);
    }
    const now = performance.now();
    this.dots = this.dots.filter((dot) => {
      const p = (now - dot.start) / WorkflowMotion.DOT_MS;
      if (p >= 1) {
        dot.g.remove();
        return false;
      }
      for (const part of dot.parts) part.style.strokeDashoffset = (-dot.len * p).toFixed(1);
      return true;
    });
    if (!this.dots.length && !this.flows.size && !this.busy) this._sync();
  }
}
