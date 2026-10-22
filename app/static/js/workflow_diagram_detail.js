/* Closing the Stats workflow diagram's node info panel (#workflow-detail-panel, opened by workflow_diagram.js
showWorkflowDetail): its close button, Esc, or a click anywhere outside it. A click on another node opens that node's
info instead, so it is not treated as outside. */
class WorkflowDetailPanel {
  constructor() {
    this.panel = document.getElementById("workflow-detail-panel");
    document.getElementById("workflow-detail-close").addEventListener("click", () => this.close());
    document.addEventListener("click", (event) => {
      if (this.isOpen() && !event.target.closest("#workflow-detail-panel, .wf-node")) this.close();
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
    d3.selectAll(".wf-node rect").attr("stroke-width", 1.5); // drop the selected node's highlight
  }
}

new WorkflowDetailPanel();
