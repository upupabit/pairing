/* The Stats "Visual chat workflow" legend (border color per app layer), split from workflow_diagram.js. It sits inside
the scrolling canvas, in the empty top-right corner beside the first nodes, as two columns: the app layers, then the
stages inside the ML engine. A new WORKFLOW_CATEGORY_COLORS/LABELS entry is picked up automatically. Clicking an item
highlights that layer's nodes (and the arrows touching them) and fades the rest; clicking it again shows all. */

class WorkflowLegend {
  static GAP = 80; // space between the legend and the nearest node
  static FADED = 0.15; // opacity of nodes/arrows outside the picked layer

  constructor(el) {
    this.el = el;
    this.active = null;
    this.el.addEventListener("click", (event) => {
      const item = event.target.closest("[data-category]");
      if (item) this.toggle(item.dataset.category);
    });
  }

  toggle(category) {
    this.active = this.active === category ? null : category;
    const shown = (cat) => !this.active || cat === this.active;
    const categoryOf = new Map(WORKFLOW_NODES.map((n) => [n.id, n.category]));
    d3.selectAll(".wf-node")
      .transition()
      .duration(150)
      .style("opacity", (d) => (shown(d.category) ? 1 : WorkflowLegend.FADED));
    d3.selectAll(".wf-edge")
      .transition()
      .duration(150)
      .style("opacity", (d) =>
        !this.active || categoryOf.get(d.from) === this.active || categoryOf.get(d.to) === this.active
          ? 1
          : WorkflowLegend.FADED,
      );
    for (const item of this.el.querySelectorAll("[data-category]")) {
      item.style.opacity = shown(item.dataset.category) ? "" : "0.4";
      item.setAttribute("aria-pressed", String(item.dataset.category === this.active));
    }
  }

  render() {
    const categories = Object.keys(WORKFLOW_CATEGORY_COLORS);
    const firstMl = categories.findIndex((c) => c.startsWith("ml_"));
    const app = firstMl === -1 ? categories : categories.slice(0, firstMl);
    const ml = firstMl === -1 ? [] : categories.slice(firstMl);
    this.el.innerHTML =
      this.column("Legend", app) +
      (ml.length ? this.column("Inside the ML engine", ml) : "") +
      `<p class="col-span-2 mt-2 border-t border-slate-800 pt-1.5 text-[11px] text-slate-500">
        Click an item to show only its nodes.
      </p>`;
  }

  column(title, categories) {
    const items = categories
      .map((category) => {
        const color = WORKFLOW_CATEGORY_COLORS[category];
        const label = escapeHtml(WORKFLOW_CATEGORY_LABELS[category] || category);
        return `<button type="button" data-category="${escapeHtml(category)}" aria-pressed="false"
          title="Show only these steps (click again to show all)"
          class="flex w-full items-center gap-2 rounded px-1 -mx-1 text-left hover:bg-slate-800 transition-opacity">
          <span class="h-3 w-3 shrink-0 rounded-sm border" style="border-color:${color};background:${color}22"></span>
          <span class="text-slate-300">${label}</span>
        </button>`;
      })
      .join("");
    return `<div class="space-y-1 min-w-0">
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-0.5">${escapeHtml(title)}</p>${items}
    </div>`;
  }

  /* In the top-right corner of the canvas, right of the top node, right-aligned with the diagram (canvas
  coordinates: node position + offset, see workflowCanvasBounds). Returns how far the diagram must move down so no
  node under the legend is covered (0 when it fits); call after render, while the view is visible, so its size is
  measurable. */
  place(nodes, offsetX, offsetY) {
    const top = nodes.reduce((a, b) => (b.y < a.y ? b : a));
    const start = offsetX + top.x + top.w + WorkflowLegend.GAP;
    const end = offsetX + Math.max(...nodes.map((n) => n.x + n.w));
    this.el.style.maxWidth = `${Math.max(end - start, 0)}px`;
    this.el.style.left = `${start}px`;
    const width = this.el.offsetWidth;
    const left = end - width;
    this.el.style.left = `${left}px`;
    this.el.style.top = `${offsetY + top.y}px`;
    const below = nodes.filter((n) => offsetX + n.x < left + width && offsetX + n.x + n.w > left);
    if (!below.length) return 0;
    const firstBelow = offsetY + Math.min(...below.map((n) => n.y));
    return Math.max(offsetY + top.y + this.el.offsetHeight + WorkflowLegend.GAP - firstBelow, 0);
  }
}
