/*
 * Stats "Visual chat workflow": starts focused on the ML engine. Every step above the "ML engine" node (the pAIring
 * app side: send, prompt build, RAG, tools...) folds into one "App steps" node, which the live view
 * (workflow_diagram_live.js) still lights up for whatever runs behind it. Clicking that node, or the toggle button,
 * opens the full diagram; the button folds it again. Also sizes the canvas to what is shown. Load before
 * workflow_diagram.js runs.
 */

class WorkflowFocus {
  static ANCHOR = "ml_engine_server";
  static GROUP = "app_steps";
  static GAP = 46; // between the folded node and the engine node
  static TOP = 24; // extra room at the top for the toggle button

  constructor(svg, root) {
    this.svg = svg;
    this.root = root;
    this.expanded = false;
    const anchor = WORKFLOW_NODES.find((n) => n.id === WorkflowFocus.ANCHOR);
    this.hidden = new Set(WORKFLOW_NODES.filter((n) => n.y <= anchor.y && n.id !== anchor.id).map((n) => n.id));
    this.anchorY = anchor.y;
    this.group = {
      id: WorkflowFocus.GROUP,
      label: `App steps (${this.hidden.size})\nclick to show`,
      category: "service",
      x: anchor.x - 20,
      y: anchor.y - 64 - WorkflowFocus.GAP,
      w: anchor.w + 40,
      h: 64,
    };
    this._drawGroup(anchor);
    this.button = document.getElementById("workflow-focus-toggle");
    this.button.addEventListener("click", () => this.toggle());
    this.apply();
  }

  /* The folded node's id while `id` is folded into it, else null (the live view groups by it). */
  groupOf(id) {
    return !this.expanded && this.hidden.has(id) ? WorkflowFocus.GROUP : null;
  }

  isShown(id) {
    return id === WorkflowFocus.GROUP ? !this.expanded : this.expanded || !this.hidden.has(id);
  }

  toggle() {
    this.expanded = !this.expanded;
    this.apply();
  }

  apply() {
    const shown = (d) => this.isShown(d.id);
    d3.selectAll(".wf-node").attr("display", (d) => (shown(d) ? null : "none"));
    d3.selectAll(".wf-edge").attr("display", (d) => (this.isShown(d.from) && this.isShown(d.to) ? null : "none"));
    d3.selectAll(".wf-annotation").attr("display", (d) => (this.expanded || d.y > this.anchorY ? null : "none"));
    this.button.textContent = this.expanded ? "Hide app steps" : `Show app steps (${this.hidden.size})`;
    this.button.setAttribute("aria-expanded", String(this.expanded));
    this.layout();
    document.dispatchEvent(new CustomEvent("workflow-focus-change"));
  }

  /* Sizes the svg to the shown nodes, the top one just under the toggle button. Width always spans every node, so
  folding never shifts the diagram sideways. */
  layout() {
    const shown = [...WORKFLOW_NODES, this.group].filter((n) => this.isShown(n.id));
    const full = workflowCanvasBounds();
    const bounds = workflowCanvasBounds(shown);
    this.svg.attr("width", full.width).attr("height", bounds.height + WorkflowFocus.TOP);
    this.root.attr("transform", `translate(${full.offsetX},${bounds.offsetY + WorkflowFocus.TOP})`);
  }

  _drawGroup(anchor) {
    const color = WORKFLOW_CATEGORY_COLORS[this.group.category];
    const g = this.root.select(".wf-nodes").insert("g", ":first-child").datum(this.group)
      .attr("class", "wf-node wf-focus-group").attr("data-id", this.group.id)
      .attr("transform", `translate(${this.group.x},${this.group.y})`)
      .style("cursor", "pointer").on("click", () => this.toggle());
    g.append("title").text("pAIring's own steps before the engine. Click to show them.");
    g.append("rect").attr("width", this.group.w).attr("height", this.group.h).attr("rx", 8)
      .attr("fill", ThemeColors.get("--color-slate-900")).attr("stroke", color).attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "6 4");
    const text = g.append("text").attr("text-anchor", "middle").attr("fill", ThemeColors.get("--color-slate-200"))
      .attr("font-size", "12px").attr("font-weight", "500");
    this.group.label.split("\n").forEach((line, i) => {
      text.append("tspan").attr("x", this.group.w / 2).attr("y", 27 + i * 15)
        .attr("fill", i ? ThemeColors.get("--color-slate-400") : null).attr("font-size", i ? "11px" : null).text(line);
    });
    const edge = { from: this.group.id, to: anchor.id, branch: false };
    this.root.select(".wf-edges").insert("path", ":first-child").datum(edge).attr("class", "wf-edge")
      .attr("d", workflowEdgePath(this.group, anchor, "v")).attr("fill", "none")
      .attr("stroke", ThemeColors.get("--color-slate-500")).attr("stroke-width", 2)
      .attr("marker-end", `url(#${WORKFLOW_ARROW_MARKER_ID})`);
  }
}
