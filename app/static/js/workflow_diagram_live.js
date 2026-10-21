/*
 * Live workflow view, the drawing half: overlays the D3 diagram (workflow_diagram.js) with what runs now, from
 * GET /api/stats/workflow/live (SSE) through WorkflowLiveState (workflow_diagram_live_state.js). Running nodes glow,
 * slow ones get an amber/red ring and a "×usual" tag. An arrow streams while a chat is busy at both its ends: thicker,
 * with "×N", when N chats use it, faster with their combined tokens/s; each finished step sends a dot in its chat's
 * colour (the mark on its status row). stats.js starts it while the view is open and stops it otherwise, so the
 * server polls Matricxon only while someone watches.
 */

class WorkflowLiveView {
  static URL = "/api/stats/workflow/live";
  static DOT_MS = 450;
  static ROWS = 4;

  constructor() {
    this.state = null;
    this.source = null;
    this.frame = null;
    this.dots = [];
    this.flows = [];
    this.built = false;
    this.collapsed = false;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.strip = document.getElementById("workflow-live-strip");
    this.strip.addEventListener("click", (event) => {
      if (event.target.closest("[data-toggle]")) {
        this.collapsed = !this.collapsed;
        this._renderStrip(this.lastView || { live: false, runs: [] });
        return;
      }
      const row = event.target.closest("[data-focus]");
      let node = row && document.querySelector(`.wf-node[data-id="${row.dataset.focus}"]`);
      if (node?.getAttribute("display") === "none") node = document.querySelector(".wf-focus-group"); // folded away
      node?.scrollIntoView({ block: "center", inline: "center", behavior: this.reduced ? "auto" : "smooth" });
    });
  }

  start() {
    if (this.source) return;
    this._build();
    this.source = new EventSource(WorkflowLiveView.URL);
    this.source.onmessage = (event) => this._render((this.lastSnapshot = JSON.parse(event.data)));
    this.source.onerror = () => this._renderStrip({ live: false, error: "Live view disconnected; retrying…", runs: [] });
    let last = performance.now();
    const tick = (t) => {
      this._animate(Math.min(t - last, 100));
      last = t;
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  stop() {
    this.source?.close();
    this.source = null;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
  }

  _build() {
    if (this.built) return;
    this.built = true;
    // Inside the edges group, after its paths: above the plain arrows, below the nodes.
    const flowLayer = d3.select(".wf-edges").append("g").attr("class", "wf-live-flows");
    this.dotLayer = d3.select(".wf-root").insert("g", ".wf-nodes").attr("class", "wf-live-dots");
    const category = new Map(d3.selectAll(".wf-node").data().map((n) => [n.id, n.category]));
    d3.selectAll(".wf-edge").each((d, i, paths) => {
      const el = flowLayer.append("path").attr("class", "wf-live-flow").attr("d", paths[i].getAttribute("d"))
        .attr("stroke", WORKFLOW_CATEGORY_COLORS[category.get(d.from)] || ThemeColors.get("--color-slate-400")).node();
      const len = el.getTotalLength();
      const mid = el.getPointAtLength(len / 2);
      const label = flowLayer.append("text").attr("class", "wf-live-count").attr("x", mid.x + 8).attr("y", mid.y - 6).node();
      this.flows.push({ key: `${d.from}>${d.to}`, from: d.from, to: d.to, base: paths[i], el, label, len, offset: 0, speed: 1 });
    });
    d3.selectAll(".wf-node").each((d, i, groups) => this._decorate(d3.select(groups[i]), d));
    this.state = new WorkflowLiveState(this.flows, (id) => window.workflowFocus?.groupOf(id) ?? null);
    // Folding or opening the app steps regroups the states at once, not on the next frame.
    document.addEventListener("workflow-focus-change", () => this.lastSnapshot && this._render(this.lastSnapshot));
  }

  _decorate(group, d) {
    const color = WORKFLOW_CATEGORY_COLORS[d.category] || ThemeColors.get("--color-slate-500");
    const live = group.insert("g", ":first-child").attr("class", "wf-live");
    live.append("rect").attr("class", "wf-live-halo").attr("x", -3).attr("y", -3).attr("width", d.w + 6)
      .attr("height", d.h + 6).attr("rx", 10).attr("stroke", color);
    live.append("rect").attr("class", "wf-live-ring").attr("x", -6).attr("y", -6).attr("width", d.w + 12)
      .attr("height", d.h + 12).attr("rx", 12);
    const top = group.append("g").attr("class", "wf-live wf-live-top");
    top.append("rect").attr("class", "wf-live-track").attr("x", 10).attr("y", d.h - 7).attr("width", d.w - 20)
      .attr("height", 3).attr("rx", 1.5);
    top.append("rect").attr("class", "wf-live-bar").attr("x", 10).attr("y", d.h - 7).attr("width", 0)
      .attr("height", 3).attr("rx", 1.5).attr("fill", color);
    const metric = top.append("g").attr("class", "wf-live-metric");
    metric.append("rect").attr("height", 17).attr("rx", 8.5).attr("fill", ThemeColors.get("--color-slate-900"))
      .attr("stroke", color).attr("stroke-width", 1);
    metric.append("text").attr("y", 12.5);
    const tag = top.append("g").attr("class", "wf-live-tag").attr("transform", "translate(8,-9)");
    tag.append("rect").attr("height", 17).attr("rx", 8.5);
    tag.append("text").attr("y", 12.5);
  }

  _render(snapshot) {
    const view = this.state.update(snapshot);
    this._renderStrip(view);
    const nodes = view.live ? view.nodes : new Map();
    d3.selectAll(".wf-node").each((d, i, groups) => this._renderNode(d3.select(groups[i]), d, nodes.get(d.id)));
    for (const flow of this.flows) {
      const edge = view.live && flow.base.getAttribute("display") !== "none" ? view.edges.get(flow.key) : null;
      flow.el.classList.toggle("on", Boolean(edge));
      flow.el.style.strokeWidth = edge ? Math.min(3 + 1.5 * (edge.count - 1), 9) : null;
      // Short arrows between neighbouring nodes skip the label: the node pills already show "×N".
      flow.label.textContent = edge && edge.count > 1 && flow.len > 80 ? `×${edge.count}` : "";
      flow.speed = edge ? edge.speed : 1;
      for (const color of edge?.dots || []) this._spawnDot(flow, color);
    }
  }

  _renderNode(group, d, state) {
    const level = state ? liveLevel(state.ratio) : "";
    group.classed("wf-live-active", Boolean(state?.active)).classed("wf-live-past", Boolean(state?.past));
    group.classed("wf-live-warn", level === "warn").classed("wf-live-crit", level === "crit");
    group.select(".wf-live-bar").attr("width", state?.share != null ? (d.w - 20) * state.share : 0);
    group.select(".wf-live-track").style("display", state?.share != null ? null : "none");
    this._pill(group.select(".wf-live-metric"), state?.text || "", (width) => `translate(${d.w - width - 10},${d.h - 9})`);
    this._pill(group.select(".wf-live-tag"), level ? `${state.ratio.toFixed(1)}× usual` : "", () => "translate(8,-9)");
  }

  _pill(pill, text, place) {
    pill.style("display", text ? null : "none");
    if (!text) return;
    const label = pill.select("text").text(text);
    const width = label.node().getComputedTextLength() + 14;
    label.attr("x", width / 2);
    pill.select("rect").attr("width", width);
    pill.attr("transform", place(width));
  }

  _spawnDot(flow, color) {
    if (this.reduced || this.dots.length > 60) return;
    const dot = this.dotLayer.append("circle").attr("class", "wf-live-dot").attr("r", 4.5).attr("fill", color)
      .style("filter", `drop-shadow(0 0 4px ${color})`);
    this.dots.push({ flow, el: dot.node(), t: 0 });
  }

  _animate(dt) {
    if (this.reduced) return;
    for (const flow of this.flows) {
      if (!flow.el.classList.contains("on")) continue;
      flow.offset -= dt * 0.03 * flow.speed;
      flow.el.style.strokeDashoffset = flow.offset;
    }
    this.dots = this.dots.filter((dot) => {
      dot.t += dt;
      if (dot.t >= WorkflowLiveView.DOT_MS) {
        dot.el.remove();
        return false;
      }
      const point = dot.flow.el.getPointAtLength((dot.t / WorkflowLiveView.DOT_MS) * dot.flow.len);
      dot.el.setAttribute("cx", point.x);
      dot.el.setAttribute("cy", point.y);
      return true;
    });
  }

  _renderStrip(view) {
    this.lastView = view;
    const status = view.live
      ? `<span class="rounded-full bg-emerald-900/70 px-2 py-0.5 font-mono text-[10px] font-semibold text-emerald-300">LIVE</span>`
      : `<span class="rounded-full bg-slate-800 px-2 py-0.5 font-mono text-[10px] font-semibold text-slate-400">OFF</span>`;
    const note = view.live
      ? "Matricxon engine"
      : view.engine ? `Live view needs the Matricxon engine (active: ${escapeHtml(view.engine)})` : "Connecting…";
    // Running chats first (oldest on top), then the latest finished ones in the room left.
    const running = view.runs.filter((r) => !r.done);
    const finished = view.runs.filter((r) => r.done).reverse();
    const shown = [...running, ...finished].slice(0, WorkflowLiveView.ROWS);
    const more = running.length - shown.filter((r) => !r.done).length;
    const rows = shown.map((run) => this._runRow(run)).join("") +
      (more > 0 ? `<p class="mt-2 text-slate-500">+${more} more running</p>` : "");
    const idle = view.live && !view.runs.length ? `<p class="mt-2 text-slate-500">No replies right now. Send a chat message to watch it here.</p>` : "";
    const error = view.error ? `<p class="mt-2 text-amber-400">${escapeHtml(view.error)}</p>` : "";
    const toggle = `<button type="button" data-toggle class="ml-auto text-slate-500 hover:text-slate-300">${this.collapsed ? "Show" : "Hide"}</button>`;
    const body = this.collapsed ? "" : `${rows}${idle}${error}`;
    this.strip.innerHTML = `<div class="flex items-center gap-2">${status}<span class="truncate text-slate-400">${note}</span>${toggle}</div>${body}`;
  }

  _runRow(run) {
    const level = (lvl) => (lvl === "crit" ? "text-rose-400" : lvl === "warn" ? "text-amber-400" : "text-slate-200");
    const cell = (label, value, cls = "text-slate-200") =>
      `<div><p class="text-[10px] uppercase tracking-wide text-slate-500">${label}</p><p class="font-mono ${cls}">${value}</p></div>`;
    return `<button type="button" ${run.focus ? `data-focus="${escapeHtml(run.focus)}"` : ""}
      class="mt-2 block w-full rounded-md border border-slate-800 px-2 py-1.5 text-left hover:bg-slate-800 ${run.done ? "opacity-60" : ""}">
      <div class="flex items-center justify-between gap-2">
        <span class="flex min-w-0 flex-1 items-center gap-1.5">
          <span class="h-2.5 w-2.5 shrink-0 rounded-full" style="background:${run.color}"></span>
          <span class="truncate text-slate-200">${escapeHtml(run.step)}</span>
        </span>
        <!-- A long model tag takes at most half the row, cut with "…"; the full name shows on hover. -->
        <span class="min-w-0 max-w-[50%] truncate font-mono text-[10px] text-slate-500"
          title="${escapeHtml(run.model)}${run.untracked ? " · a Matricxon reply not started by a chat here (a smart title, or another instance)" : ""}">
          ${run.untracked ? "untracked · " : ""}${escapeHtml(run.model)}</span>
      </div>
      <div class="mt-1 grid grid-cols-5 gap-1">
        ${cell("Elapsed", liveFormatMs(run.elapsedMs))}
        ${cell("1st token", run.ttftMs != null ? liveFormatMs(run.ttftMs) : "–", level(run.ttftLevel))}
        ${cell("Tok/s", run.tps ? run.tps.toFixed(1) : "–", level(run.tpsLevel))}
        ${cell("Tokens", run.tokens)}
        ${cell("Layer", run.layer || "–")}
      </div>
    </button>`;
  }
}
