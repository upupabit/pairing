/* The Stats workflow view's Simple / New switch (stats_workflow_switch.html): saves the admin's pick for everyone
(PUT /api/settings/workflow-view, workflow_view_setting.py) and reloads, since each view loads its own scripts. */
class WorkflowViewSwitch {
  static URL = "/api/settings/workflow-view";

  constructor(el) {
    this.el = el;
    el?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-workflow-view]");
      if (button && button.getAttribute("aria-pressed") !== "true") this.pick(button.dataset.workflowView);
    });
  }

  async pick(view) {
    this.el.style.opacity = "0.6";
    try {
      await api(WorkflowViewSwitch.URL, { method: "PUT", body: JSON.stringify({ view }) });
      location.reload();
    } catch (err) {
      this.el.style.opacity = "";
      this.el.title = `Could not switch: ${err.message || err}`;
    }
  }
}

new WorkflowViewSwitch(document.getElementById("workflow-view-switch"));
