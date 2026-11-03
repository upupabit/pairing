/* Cluster > Servers (app/templates/_servers_panel.html): the server list and "Update all servers"
 * via /api/settings/servers. Polls while that view is visible. */
class ServersPanel {
  static URL = "/api/settings/servers";
  static STATES = { updating: "Updating…", restarting: "Restarting…", done: "Updated", up_to_date: "Up to date" };

  constructor(root) {
    this.root = root;
    this.field = (name) => root.querySelector(`[data-field="${name}"]`);
    this.updateButton = root.querySelector('[data-action="update-all"]');
    this.cancelButton = root.querySelector('[data-action="cancel"]');
    this.updateButton.addEventListener("click", () => this.startUpdate());
    this.cancelButton.addEventListener("click", () => this.post("/update-all/cancel"));
    this.field("rows").addEventListener("click", (event) => this.onRowClick(event));
    this.rollout = new RolloutProgress(this.field("rollout"));
    this.refresh();
    // Every 2.5 s during an "Update all servers" (progress is shared every 3 s), else every 5 s.
    this.ticks = 0;
    setInterval(() => this.visible() && (this.running || ++this.ticks % 2 === 0) && this.refresh(), 2500);
  }

  visible() {
    return !document.getElementById("cluster-view-servers")?.classList.contains("hidden");
  }

  async refresh() {
    try {
      this.render(await api(ServersPanel.URL));
    } catch (err) {
      this.showError(err.message);
    }
  }

  async startUpdate() {
    if (!confirm("Update pAIring on every server, one at a time? Each restarts after its update.")) return;
    await this.post("/update-all");
  }

  async post(path) {
    try {
      this.render(await api(`${ServersPanel.URL}${path}`, { method: "POST" }));
    } catch (err) {
      this.showError(err.message);
    }
  }

  async onRowClick(event) {
    const button = event.target.closest('[data-action="forget"]');
    if (!button || !confirm(`Remove ${button.dataset.id} from the list?`)) return;
    try {
      await api(`${ServersPanel.URL}/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
      await this.refresh();
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
    this.running = running;
    this.updateButton.disabled = running;
    this.updateButton.classList.toggle("hidden", !overview.shared_database);
    this.cancelButton.classList.toggle("hidden", !running);
    this.rollout.render(overview.rollout, overview.servers, overview.server_time);
    this.field("single").classList.toggle("hidden", overview.shared_database);
    this.field("source-wrap").classList.toggle("hidden", !overview.shared_database); // one server: the Update tab has it
    this.field("intro").classList.toggle("hidden", !overview.shared_database);
    setHtml(this.field("rows"), this.grouped(overview.servers).map(([s, nested, last]) => this.row(s, nested, last)).join(""));
  }

  stateText(state) {
    if (!state) return "";
    const [kind, ...rest] = state.split(": ");
    const detail = rest.join(": ");
    if (kind === "needs_restart") return `Updated, restart it: ${detail}`;
    if (kind === "skipped" || kind === "error") return `${kind === "error" ? "Error" : "Skipped"}: ${detail}`;
    return ServersPanel.STATES[kind] || state;
  }

  // A server, then its local instances (same machine) under it as a tree: [server, nested?, last of its group?].
  grouped(servers) {
    const primaries = servers.filter((s) => s.is_primary);
    const machines = new Set(primaries.map((s) => s.machine));
    const instancesOf = (machine) => servers.filter((s) => !s.is_primary && s.machine === machine);
    const orphans = servers.filter((s) => !s.is_primary && !machines.has(s.machine));
    return [
      ...primaries.flatMap((p) => {
        const instances = instancesOf(p.machine);
        p.instanceCount = instances.length;
        return [[p, false, false], ...instances.map((s, i) => [s, true, i === instances.length - 1])];
      }),
      ...orphans.map((s) => [s, false, false]),
    ];
  }

  row(s, nested = false, last = false) {
    const count = s.instanceCount ? `${s.instanceCount + 1} processes` : "";
    const badges = [s.leader ? "leader" : "", s.this_server ? "this server" : "", count, !s.is_primary && !nested ? "local instance" : ""]
      .filter(Boolean)
      .map((b) => `<span class="ml-1 rounded-full border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400">${b}</span>`)
      .join("");
    const status = s.online
      ? '<span class="text-emerald-400">online</span>'
      : `<span class="text-slate-500">offline ${this.ago(s.seconds_since_seen)}</span>`;
    const version = `${escapeHtml(s.version)}${s.git_commit ? ` <span class="font-mono text-slate-500">${escapeHtml(s.git_commit)}</span>` : ""}`;
    const forget = s.online
      ? ""
      : `<button type="button" data-action="forget" data-id="${escapeHtml(s.server_id)}" class="text-slate-500 hover:text-red-400">Remove</button>`;
    // An instance hangs under its server: a tree line, and "instance" with its port instead of the full name.
    const name = nested
      ? `<span class="text-slate-600">${last ? "└" : "├"}─</span> <span class="text-slate-400">instance</span> <span class="font-mono">${escapeHtml(s.server_id.split(":").pop())}</span>`
      : `<span class="font-mono">${escapeHtml(s.server_id)}</span>`;
    return `<tr class="${nested ? "bg-slate-950/40" : ""}">
      <td class="px-3 ${nested ? "py-1.5 pl-6" : "py-2"}">${name}${badges}</td>
      <td class="px-3 py-2">${version}</td>
      <td class="px-3 py-2">${status}</td>
      <td class="px-3 py-2">${escapeHtml(this.stateText(s.update_state))}</td>
      <td class="px-3 py-2 text-right">${forget}</td>
    </tr>`;
  }

  ago(seconds) {
    if (seconds < 120) return `${seconds}s ago`;
    if (seconds < 7200) return `${Math.round(seconds / 60)} min ago`;
    if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
    return `${Math.round(seconds / 86400)} days ago`;
  }
}

// Replaces an element's HTML only when it changed, so a refresh that changes nothing doesn't redraw (and flicker).
function setHtml(el, html) {
  if (el.dataset.html !== html) {
    el.innerHTML = html;
    el.dataset.html = html;
  }
}

const serversPanelEl = document.getElementById("servers-panel");
if (serversPanelEl) new ServersPanel(serversPanelEl);
