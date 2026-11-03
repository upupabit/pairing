/* Cluster > Servers: the multi-server checklist and folders (_servers_checks.html), and this server's folders
 * and SECRET_KEY (_servers_this.html), via /api/settings/servers/checks and /this. */
class ServersChecks {
  static URL = "/api/settings/servers";
  static ICONS = { true: ["✓", "text-emerald-400"], false: ["✗", "text-red-400"], null: ["…", "text-slate-500"] };

  constructor(checksRoot, thisRoot) {
    this.checksRoot = checksRoot;
    this.thisRoot = thisRoot;
    this.checksField = (name) => checksRoot.querySelector(`[data-field="${name}"]`);
    this.thisField = (name) => thisRoot.querySelector(`[data-field="${name}"]`);
    thisRoot.querySelector('[data-action="generate"]').addEventListener("click", () => this.generate());
    thisRoot.querySelector('[data-action="fill"]').addEventListener("click", () => this.fillFromBase());
    thisRoot.querySelector('[data-action="save"]').addEventListener("click", () => this.save());
    this.restartButton = thisRoot.querySelector('[data-action="restart"]');
    this.restartButton.addEventListener("click", () => this.restart());
    this.refresh();
    this.loadThis();
    setInterval(() => this.visible() && this.refresh(), 10000);
  }

  visible() {
    return !document.getElementById("cluster-view-servers")?.classList.contains("hidden");
  }

  async refresh() {
    try {
      this.renderChecks(await api(`${ServersChecks.URL}/checks`));
    } catch (_err) {
      // Shown on the next refresh; the server list reports connection problems.
    }
  }

  renderChecks(result) {
    setHtml(this.checksField("checks"), result.checks.map((c) => this.checkRow(c)).join(""));
    const names = result.folders.length ? Object.keys(result.folders[0].folders) : [];
    this.checksField("folders-wrap").classList.toggle("hidden", !names.length);
    setHtml(
      this.checksField("folders-head"),
      `<tr><th class="px-3 py-2 text-left font-medium">Server</th>${names.map((n) => `<th class="px-3 py-2 text-left font-medium font-mono">${n}</th>`).join("")}</tr>`,
    );
    setHtml(
      this.checksField("folders"),
      result.folders
        .map((s) => `<tr><td class="px-3 py-2 font-mono">${escapeHtml(s.server_id)}</td>${names.map((n) => this.folderCell(s.folders[n])).join("")}</tr>`)
        .join(""),
    );
  }

  checkRow(check) {
    const [icon, color] = ServersChecks.ICONS[check.ok];
    const detail = check.detail ? `<p class="text-xs text-slate-400">${escapeHtml(check.detail)}</p>` : "";
    const fix = check.fix && check.ok === false ? `<p class="text-xs text-slate-500">Fix: ${escapeHtml(check.fix)}</p>` : "";
    return `<li class="flex gap-3 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
      <span class="${color} font-bold">${icon}</span>
      <div class="min-w-0"><p class="text-sm text-slate-200">${escapeHtml(check.title)}</p>${detail}${fix}</div>
    </li>`;
  }

  folderCell(folder) {
    const same = folder.same === true ? "same folder" : folder.same === false ? "not the same" : "";
    const color = folder.same === false ? "text-red-400" : "text-slate-500";
    const fs = folder.shared_fs ? "network disk" : "local disk";
    return `<td class="px-3 py-2"><span class="font-mono">${escapeHtml(folder.path)}</span><br><span class="${color}">${[same, fs].filter(Boolean).join(" · ")}</span></td>`;
  }

  async loadThis() {
    try {
      this.renderThis(await api(`${ServersChecks.URL}/this`));
    } catch (err) {
      this.thisField("status").textContent = err.message;
    }
  }

  renderThis(info) {
    this.thisField("server-id").textContent = info.server_id;
    this.thisField("folder-inputs").innerHTML = Object.entries(info.folders)
      .map(([name, f]) => {
        const pending = f.saved && f.saved !== f.running ? ` <span class="text-warning-400">(saved: ${escapeHtml(f.saved)}, after restart)</span>` : "";
        return `<label class="block text-xs font-medium text-slate-400"><span class="font-mono">${name}</span>${pending}
          <input data-folder="${name}" type="text" value="${escapeHtml(f.saved || f.running)}" spellcheck="false"
            class="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs focus:outline-none focus:border-brand-500"></label>`;
      })
      .join("");
    this.originalFolders = Object.fromEntries(Object.entries(info.folders).map(([n, f]) => [n, f.saved || f.running]));
    this.thisField("secret-state").textContent = info.secret_set
      ? "(set)"
      : info.secret_saved
        ? "(saved, used after restart)"
        : "(not set: a random key, users are logged out on every restart)";
    this.restartButton.classList.toggle("hidden", !(info.restart_needed && info.can_restart));
    if (info.restart_needed) {
      this.thisField("status").textContent = info.can_restart ? "Saved. Restart this server to use it." : `Saved. Restart it: ${info.restart_hint}`;
    }
  }

  // One shared folder for all 4: <base>/knowledge, /attachments, /avatars, /generated_images.
  fillFromBase() {
    const base = this.thisField("base").value.trim().replace(/\/+$/, "");
    if (!base.startsWith("/")) {
      this.thisField("status").textContent = "The shared folder must be an absolute path, e.g. /mnt/pairing.";
      return;
    }
    const subfolders = { KNOWLEDGE_DIR: "knowledge", ATTACHMENTS_DIR: "attachments", AVATARS_DIR: "avatars", IMAGES_DIR: "generated_images" };
    this.thisRoot.querySelectorAll("[data-folder]").forEach((input) => {
      input.value = `${base}/${subfolders[input.dataset.folder]}`;
    });
    this.thisField("status").textContent = "Filled in. Check them, then Save.";
  }

  generate() {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    this.thisField("secret").value = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async save() {
    const folders = {};
    this.thisRoot.querySelectorAll("[data-folder]").forEach((input) => {
      if (input.value.trim() !== this.originalFolders[input.dataset.folder]) folders[input.dataset.folder] = input.value.trim();
    });
    const secret = this.thisField("secret").value.trim();
    const body = { folders, ...(secret ? { secret_key: secret } : {}) };
    if (!Object.keys(folders).length && !secret) {
      this.thisField("status").textContent = "Nothing changed.";
      return;
    }
    if (secret && !confirm("Save this SECRET_KEY? After the restart everyone signs in again once.")) return;
    try {
      this.renderThis(await api(`${ServersChecks.URL}/this`, { method: "PUT", body: JSON.stringify(body) }));
      this.thisField("secret").value = "";
    } catch (err) {
      this.thisField("status").textContent = err.message;
    }
  }

  async restart() {
    if (!confirm("Restart this server now? Its replies in progress stop.")) return;
    this.restartButton.disabled = true;
    try {
      await api("/api/settings/update/pairing/restart", { method: "POST" });
      this.thisField("status").textContent = "Restarting… this page reloads when it is back.";
      await ServersChecks.waitForRestart();
      window.location.reload();
    } catch (err) {
      this.thisField("status").textContent = `Could not restart: ${err.message}`;
      this.restartButton.disabled = false;
    }
  }
}

ServersChecks.waitForRestart = async () => {
  // Down, then back up (any answer below 500), as UpdatePanel.waitForRestart.
  const up = async () => {
    try {
      return (await fetch("/login", { cache: "no-store" })).status < 500;
    } catch (_err) {
      return false;
    }
  };
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let i = 0; i < 30 && (await up()); i++) await sleep(500);
  for (let i = 0; i < 120 && !(await up()); i++) await sleep(1000);
};

const serversChecksEl = document.getElementById("servers-checks");
const serversThisEl = document.getElementById("servers-this");
if (serversChecksEl && serversThisEl) new ServersChecks(serversChecksEl, serversThisEl);
