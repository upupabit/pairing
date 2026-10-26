/*
 * Stats > Workflow analysis: GET /api/stats/workflow/live/analysis (services/workflow_analysis.py), the last minutes of
 * the live workflow view summed up: what needs attention, then the nodes, models and pAIring steps behind it. Each
 * fetch also takes a sample, so the history keeps growing while this page is open (stats.js refreshes it).
 */

const ANALYSIS_LEVELS = {
  crit: { label: "Needs attention", cls: "border-red-500/50 bg-red-500/5", text: "text-red-400" },
  warn: { label: "Worth a look", cls: "border-pink-500/50 bg-pink-500/5", text: "text-pink-400" },
  info: { label: "Good to know", cls: "border-sky-500/40 bg-sky-500/5", text: "text-sky-400" },
};
const ANALYSIS_MAX_FINDINGS = 30;

function _analysisDuration(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`;
}

function _analysisPct(share) {
  return share ? `${Math.round(share * 100)}%` : "–";
}

/* "rag_rerank" -> its diagram label, when the diagram data is loaded. */
function _analysisStepLabel(id) {
  const node = typeof WORKFLOW_NODES !== "undefined" && WORKFLOW_NODES.find((n) => n.id === id);
  return node ? node.label.split("\n")[0] : id;
}

/* A step finding names the step by its id; show the diagram's label instead. */
function _analysisTitle(f) {
  const label = f.subject ? _analysisStepLabel(f.subject) : f.subject;
  return label && label !== f.subject ? f.title.replace(f.subject, label) : f.title;
}

function _analysisTable(title, hint, headers, rows) {
  if (!rows.length) return "";
  const head = headers.map((h, i) => `<th class="px-3 py-2 font-medium ${i ? "text-right" : "text-left"}">${h}</th>`).join("");
  const body = rows
    .map((cells) => `<tr class="border-t border-slate-800">${cells.map((c, i) =>
      `<td class="px-3 py-1.5 ${i ? "text-right font-mono" : "max-w-[18rem] truncate"}">${c}</td>`).join("")}</tr>`)
    .join("");
  return `<div><h3 class="text-sm font-semibold text-slate-200">${title}</h3><p class="mb-2 text-xs text-slate-500">${hint}</p>
    <div class="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900"><table class="w-full text-xs text-slate-300">
    <thead class="text-slate-500"><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function _analysisFindings(findings) {
  if (!findings.length) {
    return `<p class="rounded-lg border border-warning-500/50 bg-slate-900 px-4 py-3 text-sm text-warning-400">Nothing needs attention at the moment</p>`;
  }
  const cards = findings.slice(0, ANALYSIS_MAX_FINDINGS).map((f) => {
    const level = ANALYSIS_LEVELS[f.level] || ANALYSIS_LEVELS.info;
    return `<div class="rounded-lg border px-4 py-2.5 ${level.cls}">
      <p class="text-sm"><span class="mr-2 text-[10px] font-semibold uppercase tracking-wide ${level.text}">${level.label}</span>
      <span class="break-words text-slate-100">${escapeHtml(_analysisTitle(f))}</span></p>
      <p class="mt-0.5 break-words text-xs text-slate-400">${escapeHtml(f.detail)}</p></div>`;
  });
  const more = findings.length - ANALYSIS_MAX_FINDINGS;
  return cards.join("") + (more > 0 ? `<p class="text-xs text-slate-500">+${more} more</p>` : "");
}

function renderWorkflowAnalysis(report) {
  const el = document.getElementById("workflow-analysis-content");
  if (!report.polls) {
    el.innerHTML = `<p class="text-sm text-slate-400">No data yet. It is collected while this page or the Visual chat workflow is open, with the Matricxon engine.</p>`;
    return;
  }
  const tiles = document.createElement("div");
  tiles.className = "grid grid-cols-2 gap-3 sm:grid-cols-4";
  tiles.append(
    statTile(_analysisDuration(report.covered_seconds), `watched, of the last ${_analysisDuration(report.window_seconds)}`),
    statTile(report.nodes_seen, "Matricxon nodes"),
    statTile(report.replies_finished, "replies finished"),
    statTile(report.findings.filter((f) => f.level !== "info").length, "things to check"),
  );
  const nodes = report.nodes.map((n) => [
    escapeHtml(liveNodeName(n.host)), n.running.toFixed(1), n.tokens_per_second?.toFixed(1) ?? "–",
    n.slowness ? `${n.slowness.toFixed(1)}×` : "–", _analysisPct(n.slow_share), _analysisPct(n.queued_share), _analysisPct(n.down_share),
  ]);
  const models = report.models.map((m) => [
    escapeHtml(m.model), m.replies, m.first_token_seconds != null ? `${m.first_token_seconds.toFixed(1)}s` : "–",
    m.tokens_per_second?.toFixed(1) ?? "–", m.loads ? `${m.loads} · ${Math.round(m.load_seconds)}s` : "–", _analysisPct(m.reuse_share),
  ]);
  const steps = report.steps.map((s) => [
    escapeHtml(_analysisStepLabel(s.step)), s.runs, liveFormatMs(s.median_ms), liveFormatMs(s.p90_ms), s.usual_ms ? liveFormatMs(s.usual_ms) : "–",
  ]);
  const moreNodes = report.nodes_more ? ` ${report.nodes_more} more nodes are not listed.` : "";
  el.replaceChildren(tiles);
  el.insertAdjacentHTML("beforeend", `<div class="space-y-2">${_analysisFindings(report.findings)}</div>` +
    _analysisTable("Nodes", `Worth a look first: unreachable, then slow, then queueing.${moreNodes}`,
      ["Node", "Replies at once", "Tok/s", "Slower than usual", "Time slow", "Queued", "Unreachable"], nodes) +
    _analysisTable("Models", "Replies that finished in the window.", ["Model", "Replies", "1st token", "Tok/s", "Loads", "Cache reuse"], models) +
    _analysisTable("pAIring steps", "This instance's chats; usual is the step's slow-tenth time.", ["Step", "Chats", "Median", "p90", "Usual"], steps));
}

/* The view's heading, report and error slots, made on first load. */
function _analysisView() {
  const view = document.getElementById("stats-view-analysis");
  if (!view.children.length) {
    view.innerHTML = `<h2 class="text-lg font-semibold text-slate-100">Workflow analysis</h2>
      <p id="workflow-analysis-error" class="hidden text-sm text-red-400"></p>
      <div id="workflow-analysis-content" class="space-y-8"></div>`;
  }
}

async function loadWorkflowAnalysis() {
  _analysisView();
  const errorEl = document.getElementById("workflow-analysis-error");
  try {
    renderWorkflowAnalysis(await api("/api/stats/workflow/live/analysis"));
    errorEl.classList.add("hidden");
  } catch (err) {
    // A refresh can fail for a moment (pAIring restarting, a dropped connection): keep the last report and say so
    // quietly; only an empty page shows the error in red.
    const shown = document.getElementById("workflow-analysis-content").children.length > 0;
    errorEl.className = shown ? "text-xs text-amber-500" : "text-sm text-red-400";
    errorEl.textContent = shown ? `Could not refresh (${err.message}). Showing the last result; retrying.` : err.message;
  }
}
