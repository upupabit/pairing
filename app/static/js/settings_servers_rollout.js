/* The "Update all" progress card: pAIring servers (Cluster > Servers, ServersPanel, noun "server") and Matricxon
 * nodes (Cluster > Update nodes, cluster_update.js, noun "node"). One overall bar, then each one in update order
 * with its stage, its update step and how long it took. */
class RolloutProgress {
  static BAR_COLORS = { running: "bg-brand-500", finished: "bg-pink-600", stopped: "bg-red-500", cancelled: "bg-slate-500" };
  static STAGES = ["Download and install", "Restart", "Back online"];
  static SPINNER = `<svg class="mx-0.5 h-4 w-4 shrink-0 animate-spin text-brand-400" viewBox="0 0 24 24" fill="none">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>`;

  constructor(root, noun = "server") {
    this.root = root;
    this.noun = noun;
    this.titles = {
      running: `Updating all ${noun}s`,
      finished: `All ${noun}s updated`,
      stopped: `Update of all ${noun}s stopped`,
      cancelled: `Update of all ${noun}s cancelled`,
    };
    this.clockOffset = 0;
    setInterval(() => this.tick(), 1000);
  }

  render(rollout, servers, serverTime) {
    this.root.classList.toggle("hidden", !rollout);
    if (!rollout) return;
    if (serverTime) this.clockOffset = serverTime - Date.now() / 1000;
    const byId = Object.fromEntries(servers.map((s) => [s.server_id, s]));
    const order = rollout.order.length ? rollout.order : [...Object.keys(rollout.results), rollout.current, ...rollout.queue].filter(Boolean);
    const rows = order.map((id, i) => this.serverRow(id, i, rollout, byId[id]));
    const fraction = order.length ? rows.reduce((sum, r) => sum + r.fraction, 0) / order.length : 0;
    const percent = rollout.status === "finished" ? 100 : Math.floor(fraction * 100);
    const done = Object.keys(rollout.results).length;
    const ended = rollout.finished_at ? ` · ended ${this.ago(rollout.finished_at)}` : "";
    const elapsed = rollout.started_at && rollout.status === "running"
      ? ` · <span data-since="${rollout.started_at}">${this.duration(this.now() - rollout.started_at)}</span>`
      : rollout.started_at && rollout.finished_at ? ` · took ${this.duration(rollout.finished_at - rollout.started_at)}` : "";
    // A server's error is already on its row; the box is for the rest, such as a server that never finished.
    const onRow = rollout.current && rollout.results[rollout.current]?.startsWith("error");
    const message = rollout.status === "stopped" && rollout.message && !onRow
      ? `<p class="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">${escapeHtml(rollout.message)}</p>`
      : "";
    setHtml(this.root, `
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="flex items-center gap-2 text-sm font-semibold text-slate-100">
          ${rollout.status === "running" ? RolloutProgress.SPINNER : this.statusIcon(rollout.status)}
          ${this.titles[rollout.status] || escapeHtml(rollout.status)}</p>
        <p class="text-xs text-slate-400">${done} of ${order.length} ${this.noun}${order.length === 1 ? "" : "s"}${elapsed}${ended}</p>
      </div>
      <div class="flex items-center gap-3">
        <div class="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-800">
          <div class="h-full rounded-full ${RolloutProgress.BAR_COLORS[rollout.status] || "bg-slate-500"} transition-all duration-700" style="width: ${percent}%"></div>
        </div>
        <span class="w-10 text-right text-xs font-medium tabular-nums text-slate-300">${percent}%</span>
      </div>
      ${message}
      <ol class="divide-y divide-slate-800 rounded-lg border border-slate-800">${rows.map((r) => r.html).join("")}</ol>`);
  }

  // One server: its part of the overall bar (0 to 1) and its row.
  serverRow(id, index, rollout, server) {
    const result = rollout.results[id];
    const isCurrent = rollout.current === id && !result;
    const state = isCurrent ? server?.update_state || "updating" : result;
    const kind = state ? state.split(": ")[0] : "waiting";
    const detail = state && state.includes(": ") ? state.split(": ").slice(1).join(": ") : "";
    const progress = isCurrent ? server?.update_progress : null;
    let fraction = 0;
    let stage = -1;
    if (["done", "up_to_date", "needs_restart", "skipped", "error"].includes(kind)) fraction = 1;
    else if (kind === "updating") {
      stage = 0;
      const step = progress ? (progress.step - 1 + (progress.percent || 0) / 100) / (progress.total_steps || 3) : 0;
      fraction = 0.7 * Math.min(1, step);
    } else if (kind === "restarting") [stage, fraction] = [1, 0.85];
    else if (kind === "rejoining") [stage, fraction] = [2, 0.95];
    const texts = {
      waiting: rollout.status === "running" ? "Waiting" : "Not updated",
      updating: progress ? `Step ${progress.step} of ${progress.total_steps}: ${progress.label}${progress.percent != null ? ` ${progress.percent}%` : ""}` : "Starting the update…",
      restarting: "Restarting with the new version…",
      rejoining: "Back up, rejoining the cluster…",
      done: "Updated and back online",
      up_to_date: "Already up to date",
      needs_restart: `Updated, restart it yourself: ${detail}`,
      skipped: `Skipped: ${detail}`,
      error: `Error: ${detail}`,
    };
    const color = { error: "text-red-400", needs_restart: "text-warning-400", skipped: "text-warning-400", waiting: "text-slate-500" }[kind] || "text-slate-300";
    const time = isCurrent && rollout.current_since
      ? `<span data-since="${rollout.current_since}">${this.duration(this.now() - rollout.current_since)}</span>`
      : rollout.durations?.[id] != null ? this.duration(rollout.durations[id]) : "";
    const badge = server?.leader ? '<span class="ml-1 rounded-full border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400">leader</span>' : "";
    const html = `<li class="px-3 py-2.5 ${isCurrent ? "bg-brand-500/5" : ""}">
      <div class="flex items-center gap-3">
        ${isCurrent ? RolloutProgress.SPINNER : this.stepIcon(kind, index)}
        <div class="min-w-0 flex-1">
          <p class="text-sm text-slate-200"><span class="font-mono">${escapeHtml(id)}</span>${badge}</p>
          <p class="text-xs ${color}">${escapeHtml(texts[kind] || state)}</p>
        </div>
        <span class="text-xs tabular-nums text-slate-500">${time}</span>
      </div>
      ${isCurrent ? this.stages(stage, progress) : ""}
    </li>`;
    return { fraction, html };
  }

  // The current server's three stages, and its step's own bar while it downloads and installs.
  stages(active, progress) {
    const chips = RolloutProgress.STAGES.map((label, i) => {
      const cls = i < active ? "border-emerald-500/50 text-emerald-400" : i === active ? "border-brand-500 text-brand-400" : "border-slate-700 text-slate-500";
      return `<span class="rounded-full border px-2 py-0.5 ${cls}">${i < active ? "✓ " : ""}${label}</span>`;
    }).join('<span class="text-slate-600">→</span>');
    const bar = active === 0 && progress?.percent != null
      ? `<div class="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800"><div class="h-full rounded-full bg-brand-400 transition-all duration-700" style="width: ${progress.percent}%"></div></div>`
      : "";
    return `<div class="ml-7 mt-2"><div class="flex flex-wrap items-center gap-1.5 text-[11px]">${chips}</div>${bar}</div>`;
  }

  stepIcon(kind, index) {
    const icons = {
      done: ["✓", "bg-emerald-500/15 text-emerald-400"],
      up_to_date: ["✓", "bg-emerald-500/15 text-emerald-400"],
      needs_restart: ["!", "bg-warning-500/15 text-warning-400"],
      skipped: ["–", "bg-warning-500/15 text-warning-400"],
      error: ["✗", "bg-red-500/15 text-red-400"],
      cancelled: ["–", "bg-slate-700 text-slate-300"],
    };
    const [text, cls] = icons[kind] || [String(index + 1), "bg-slate-800 text-slate-400"];
    return `<span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${cls}">${text}</span>`;
  }

  statusIcon(status) {
    return this.stepIcon({ finished: "done", stopped: "error", cancelled: "cancelled" }[status], 0);
  }

  // Elapsed times count up between polls.
  tick() {
    this.root.querySelectorAll("[data-since]").forEach((el) => {
      el.textContent = this.duration(this.now() - Number(el.dataset.since));
    });
  }

  now() {
    return Date.now() / 1000 + this.clockOffset;
  }

  duration(seconds) {
    const s = Math.max(0, Math.round(seconds));
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  }

  ago(epoch) {
    const s = Math.max(0, Math.round(this.now() - epoch));
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} days ago`;
  }
}
