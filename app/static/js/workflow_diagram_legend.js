/* The Stats "Visual chat workflow" legend (border color per app layer), split from workflow_diagram.js. It floats over
the top of the view (stats.html), as two columns: the app layers, then the stages inside the ML engine. A new WORKFLOW_CATEGORY_COLORS/LABELS entry is picked up automatically. Clicking an item
highlights that layer's nodes (and the arrows touching them) and fades the rest; clicking it again shows all. Hide/Show
collapses it to one line, like the live status box (workflow_diagram_live.js). */

class WorkflowLegend {
  static FADED = 0.15; // opacity of nodes/arrows outside the picked layer

  constructor(el) {
    this.el = el;
    this.active = null;
    this.collapsed = true; // starts as a one-line "Legend · Show" chip
    this.el.addEventListener("click", (event) => {
      if (event.target.closest("[data-toggle]")) {
        this.collapsed = !this.collapsed;
        this.render();
        return;
      }
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
    window.workflowCards?.fade(this.active, String(WorkflowLegend.FADED));
    for (const item of this.el.querySelectorAll("[data-category]")) {
      item.style.opacity = shown(item.dataset.category) ? "" : "0.4";
      item.setAttribute("aria-pressed", String(item.dataset.category === this.active));
    }
  }

  render() {
    const toggle = `<button type="button" data-toggle class="ml-auto text-slate-500 hover:text-slate-300">${this.collapsed ? "Show" : "Hide"}</button>`;
    if (this.collapsed) {
      this.el.innerHTML = `<div class="col-span-2 flex items-center gap-4">
        <span class="text-xs font-semibold uppercase tracking-wide text-slate-400">Legend</span>${toggle}</div>`;
      return;
    }
    const categories = Object.keys(WORKFLOW_CATEGORY_COLORS);
    const firstMl = categories.findIndex((c) => c.startsWith("ml_"));
    const app = firstMl === -1 ? categories : categories.slice(0, firstMl);
    const ml = firstMl === -1 ? [] : categories.slice(firstMl);
    this.el.innerHTML =
      `<div class="col-span-2 flex -mb-1">${toggle}</div>` +
      this.column("Legend", app) +
      (ml.length ? this.column("Inside the ML engine", ml) : "") +
      `<p class="col-span-2 mt-2 border-t border-slate-800 pt-1.5 text-[11px] text-slate-500">
        Click an item to show only its nodes.
      </p>`;
    for (const item of this.el.querySelectorAll("[data-category]")) {
      item.style.opacity = !this.active || item.dataset.category === this.active ? "" : "0.4";
      item.setAttribute("aria-pressed", String(item.dataset.category === this.active));
    }
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
}
