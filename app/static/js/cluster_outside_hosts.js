/* Cluster page > Non-cluster hosts (app/templates/_cluster_outside_hosts.html): lists the Matricxon hosts pAIring keeps
   outside the running cluster and removes the selected ones in one save. Uses api and escapeHtml from app.js. */
class OutsideHostsView {
  static URL = "/api/cluster/outside-hosts";
  static PLACES = { local: "this pAIring's Matricxon", remote: "remote hosts", cluster: "cluster nodes", voter: "voter list", remembered: "remembered id only" };

  constructor() {
    this.rows = document.getElementById("outside-hosts-rows");
    this.summary = document.getElementById("outside-hosts-summary");
    this.all = document.getElementById("outside-hosts-all");
    this.removeButton = document.getElementById("outside-hosts-remove");
    this.reset = document.getElementById("outside-hosts-reset");
    this.resets = document.getElementById("outside-hosts-resets");
    document.getElementById("outside-hosts-refresh").addEventListener("click", () => this.load());
    document.querySelector('.cluster-nav-btn[data-view="outside"]').addEventListener("click", () => this.load());
    this.removeButton.addEventListener("click", () => this.remove());
    this.all.addEventListener("change", () => {
      this.boxes().forEach((box) => (box.checked = this.all.checked));
      this.sync();
    });
    this.rows.addEventListener("change", () => this.sync());
  }

  boxes() {
    return [...this.rows.querySelectorAll("input[data-host]:not(:disabled)")];
  }

  selected() {
    return this.boxes().filter((box) => box.checked).map((box) => box.dataset.host);
  }

  sync() {
    const boxes = this.boxes();
    const picked = this.selected().length;
    this.removeButton.disabled = !picked;
    this.removeButton.textContent = picked ? `Remove selected (${picked})` : "Remove selected";
    this.all.checked = picked > 0 && picked === boxes.length;
  }

  static state(host) {
    if (host.managed) return "pAIring runs it: switch Matricxon to remote mode to remove it";
    const reach = host.reachable ? "answers" : "not reachable";
    return host.consensus ? `${reach} · still set up for a cluster` : reach;
  }

  render(list) {
    this.rows.innerHTML = list.hosts
      .map((h) => {
        const places = h.places.map((p) => OutsideHostsView.PLACES[p] || p).join(", ");
        const tone = h.reachable ? "text-emerald-400" : "text-slate-500";
        return `<tr><td class="px-3 py-1.5"><input type="checkbox" data-host="${escapeHtml(h.host)}" ${h.managed ? "disabled" : ""} class="rounded border-slate-600 bg-slate-950"></td>` +
          `<td class="px-3 py-1.5 font-mono break-all">${escapeHtml(h.host)}</td><td class="px-3 py-1.5 text-slate-400">${escapeHtml(places)}</td>` +
          `<td class="px-3 py-1.5 ${tone}">${escapeHtml(OutsideHostsView.state(h))}</td></tr>`;
      })
      .join("");
    if (!list.known) this.summary.textContent = "No voter answers, so pAIring can't tell which hosts are outside the cluster. Try again when the cluster is up.";
    else if (!list.hosts.length) this.summary.textContent = list.cluster ? "Every host pAIring keeps is a node of the cluster." : "pAIring keeps no Matricxon hosts.";
    else this.summary.textContent = list.cluster ? `${list.hosts.length} host(s) outside the cluster.` : `Cluster mode is off: ${list.hosts.length} remote host(s).`;
    this.all.checked = false;
    this.sync();
  }

  async load() {
    this.summary.textContent = "Loading…";
    try {
      this.render(await api(OutsideHostsView.URL));
    } catch (error) {
      this.summary.textContent = error.message;
    }
  }

  showResets(resets) {
    this.resets.innerHTML = resets
      .map((r) => `<li class="${r.ok ? "text-emerald-400" : "text-warning-400"}">${escapeHtml(r.host)}: ${r.ok ? "reset to a fresh install (restarting)" : escapeHtml("not reset: " + r.reason)}</li>`)
      .join("");
    this.resets.classList.toggle("hidden", !resets.length);
  }

  async remove() {
    const hosts = this.selected();
    const reset = this.reset.checked;
    const also = reset ? "\n\nThe reachable ones are also reset to a fresh install." : "";
    if (!hosts.length || !confirm(`Remove ${hosts.length} host(s) from pAIring?\n\n${hosts.join("\n")}${also}`)) return;
    this.removeButton.disabled = true;
    this.summary.textContent = "Removing…";
    try {
      const result = await api(`${OutsideHostsView.URL}/remove`, { method: "POST", body: JSON.stringify({ hosts, reset }) });
      this.render(result.state);
      this.summary.textContent = `Removed ${result.removed.length} host(s). ` + this.summary.textContent;
      this.showResets(result.resets);
    } catch (error) {
      this.summary.textContent = error.message;
      this.sync();
    }
  }
}

new OutsideHostsView();
