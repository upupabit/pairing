/* Cluster > Matricxon > Update nodes (_cluster_update_view.html): every node's version and "Update all nodes",
 * one at a time, via /api/cluster/update-all (services/matricxon_rollout.py). The progress card is the pAIring
 * servers' one (settings_servers_rollout.js). Polls while the view is visible. */
class ClusterUpdatePanel {
  static URL = "/api/cluster/update-all";

  constructor(root) {
    this.root = root;
    this.field = (name) => root.querySelector(`[data-field="${name}"]`);
    this.updateButton = root.querySelector('[data-action="update-all"]');
    this.cancelButton = root.querySelector('[data-action="cancel"]');
    this.updateButton.addEventListener("click", () => this.startUpdate());
    this.cancelButton.addEventListener("click", () => this.post("/cancel"));
    this.rollout = new RolloutProgress(this.field("rollout"), "node");
    this.running = false;
    this.ticks = 0;
    // Every 2.5 s while it runs, else every 5 s; the node versions every 30 s and when a rollout ends.
    setInterval(() => this.visible() && (this.running || ++this.ticks % 2 === 0) && this.refresh(), 2500);
    setInterval(() => this.visible() && this.loadNodes(), 30000);
    this.wasVisible = false;
    setInterval(() => this.onShow(), 500);
  }

  visible() {
    return !document.getElementById("cluster-view-update")?.classList.contains("hidden");
  }

  // The first time the view opens (and each time again), load at once.
  onShow() {
    const now = this.visible();
    if (now && !this.wasVisible) {
      this.refresh();
      this.loadNodes();
    }
    this.wasVisible = now;
  }

  async refresh() {
    try {
      this.render(await api(ClusterUpdatePanel.URL));
    } catch (err) {
      this.showError(err.message);
    }
  }

  async loadNodes() {
    try {
      setHtml(this.field("nodes"), (await api(`${ClusterUpdatePanel.URL}/nodes`)).map((n) => this.nodeRow(n)).join(""));
    } catch (err) {
      this.showError(err.message);
    }
  }

  async startUpdate() {
    if (!confirm("Update Matricxon on every node, one at a time? Each restarts after its update.")) return;
    await this.post("");
  }

  async post(path) {
    try {
      this.render(await api(`${ClusterUpdatePanel.URL}${path}`, { method: "POST" }));
    } catch (err) {
      this.showError(err.message);
    }
  }

  showError(message) {
    const el = this.field("error");
    el.textContent = message || "";
    el.classList.toggle("hidden", !message);
  }

  render(overview) {
    this.showError("");
    const running = overview.rollout?.status === "running";
    if (this.running && !running) this.loadNodes(); // new versions after it ends
    this.running = running;
    this.updateButton.disabled = running;
    this.cancelButton.classList.toggle("hidden", !running);
    this.rollout.render(overview.rollout, overview.servers, overview.server_time);
  }

  nodeRow(node) {
    const leader = node.leader ? '<span class="ml-1 rounded-full border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400">leader</span>' : "";
    const version = node.version
      ? `${escapeHtml(node.version)}${node.commit ? ` <span class="font-mono text-slate-500">${escapeHtml(node.commit)}</span>` : ""}`
      : '<span class="text-slate-500">—</span>';
    const status = node.reachable
      ? '<span class="text-emerald-400">online</span>'
      : `<span class="text-red-400">not reachable</span>`;
    return `<tr>
      <td class="px-3 py-2 font-mono">${escapeHtml(node.host)}${leader}</td>
      <td class="px-3 py-2">${version}</td>
      <td class="px-3 py-2">${status}</td>
    </tr>`;
  }
}

const clusterUpdateEl = document.getElementById("cluster-update");
if (clusterUpdateEl) new ClusterUpdatePanel(clusterUpdateEl);
