/* Closing the Stats workflow diagram's node info panel (#workflow-detail-panel, opened by workflow_diagram.js
showWorkflowDetail): its close button, Esc, or a click anywhere outside it. A click on another node or card opens its
info instead, so it is not treated as outside. */
class WorkflowDetailPanel {
  constructor() {
    this.panel = document.getElementById("workflow-detail-panel");
    document.getElementById("workflow-detail-close").addEventListener("click", () => this.close());
    document.addEventListener("click", (event) => {
      if (this.isOpen() && !event.target.closest("#workflow-detail-panel, .wf-node, .wf-card")) this.close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.isOpen()) this.close();
    });
  }

  isOpen() {
    return !this.panel.classList.contains("hidden");
  }

  close() {
    this.panel.classList.add("hidden");
    workflowSelect(null); // drop the selected node's highlight
  }
}

new WorkflowDetailPanel();

/* Shared by both views; each view's renderer has its own workflowSelect (the highlight). */
/* The category label uses CSS `uppercase`, which would also capitalize every letter of the stylized app name (APP_NAME in workflow_diagram_data.js, e.g. "pAIring"). Escapes the label, then wraps APP_NAME in text-transform:none to keep its casing. */
function formatCategoryLabel(label) {
  return escapeHtml(label).replace(
    new RegExp(APP_NAME, "g"),
    `<span style="text-transform:none">${APP_NAME}</span>`
  );
}

function showWorkflowDetail(node) {
  document.getElementById("workflow-detail-content").innerHTML = `
    <div class="flex items-center justify-between gap-2 pr-7">
      <p class="text-xs font-semibold uppercase tracking-wide" style="color:${WORKFLOW_CATEGORY_COLORS[node.category]}">
        ${formatCategoryLabel(WORKFLOW_CATEGORY_LABELS[node.category] || node.category)}
      </p>
      <span class="shrink-0 rounded-full border border-slate-700 px-2 py-0.5 text-xs font-mono text-slate-300">
        ${escapeHtml(node.detail.server)}
      </span>
    </div>
    <h3 class="text-base font-semibold text-slate-100 mt-1">${escapeHtml(node.detail.title)}</h3>
    <p class="text-xs font-mono text-slate-500 mt-1">${escapeHtml(node.detail.location)}</p>
    <p class="text-sm text-slate-300 mt-3 leading-relaxed">${escapeHtml(node.detail.body)}</p>
    ${renderWorkflowLearn(node.id)}
  `;
  document.getElementById("workflow-detail-panel").classList.remove("hidden");
  workflowSelect(node.id);
}
