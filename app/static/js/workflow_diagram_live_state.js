/*
 * Live workflow view, the logic half: turns one GET /api/stats/workflow/live snapshot into node, arrow and dot states
 * (workflow_diagram_live.js draws them). Works per chat: a chat is one pAIring run (live_workflow_bus.py) joined to
 * its Matricxon reply (GET /api/live) by request id; a Matricxon reply no run claims (a smart title, another
 * instance) is a chat of its own. An arrow flows only when both its ends are busy for the same chat, so many chats
 * never draw a stream between unrelated steps. Engine stage names: workflow_diagram_live_map.js.
 */

const LIVE_WARN_RATIO = 1.5;
const LIVE_CRIT_RATIO = 2.5;
const LIVE_RECENT_MS = 1500; // a node just finished or pulsed stays busy this long, so its arrows still flow
const LIVE_BASE_TPS = 10; // stream speed 1 at this many tokens/s
// Chat colours for dots and status rows; amber/red stay free for the slow warnings.
const LIVE_CHAT_COLORS = ["#38bdf8", "#a78bfa", "#34d399", "#f472b6", "#a3e635", "#22d3ee", "#818cf8", "#2dd4bf"];

function liveFormatMs(ms) {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`;
}

function liveLevel(ratio) {
  if (ratio >= LIVE_CRIT_RATIO) return "crit";
  return ratio >= LIVE_WARN_RATIO ? "warn" : "";
}

class WorkflowLiveState {
  /* `edges`: [{from, to}] as drawn; `groupOf(id)`: the folded node `id` shows through, or null. */
  constructor(edges, groupOf = () => null) {
    this.edges = edges;
    this.groupOf = groupOf;
    this.counts = new Map();
    this.recentUntil = new Map();
    this.colors = new Map();
    this.nextColor = 0;
  }

  update(snapshot, now = performance.now()) {
    this.now = now;
    this.nodes = new Map();
    const chats = this._chats(snapshot);
    for (const chat of chats) {
      if (chat.run) this._applyRun(chat, snapshot.usual_ms);
      if (chat.request) this._applyEngine(chat, chat.request);
      this._applyGroups(chat);
    }
    const crowd = this._crowdCounts(snapshot.crowd);
    for (const [id, count] of crowd) {
      const node = this._node(id);
      node.extra = count;
      node.past = false;
    }
    for (const node of this.nodes.values()) {
      const count = node.chats.size + (node.extra || 0);
      node.active = count > 0;
      if (count > 1) node.text = `×${count}${node.text ? ` · ${node.text}` : ""}`;
    }
    const nodeCount = snapshot.engine_node_count || 0;
    if (nodeCount > 1) this._labelEngineHosts(chats, snapshot.crowd);
    return {
      live: snapshot.live,
      engine: snapshot.engine,
      error: snapshot.engine_error,
      nodeCount,
      moreRunning: snapshot.crowd?.running || 0,
      nodes: this.nodes,
      edges: this._edges(chats, crowd, snapshot.crowd),
      runs: chats.map((chat) => liveChatSummary(chat, nodeCount > 1)),
    };
  }

  /* Cluster: the ML engine node names the Matricxon node its running replies are on, or how many nodes. */
  _labelEngineHosts(chats, crowd) {
    const node = this.nodes.get("ml_engine_server");
    const hosts = new Set(chats.filter((c) => !c.done && c.request).map((c) => c.request.host));
    const busy = crowd ? crowd.busy_nodes : hosts.size;
    if (!node || !busy) return;
    const name = hosts.size ? liveNodeName([...hosts][0]) : "";
    const where = busy > 1 || !name ? `${busy} nodes` : name.length > 18 ? `${name.slice(0, 17)}…` : name;
    node.text = node.text ? `${node.text} · ${where}` : where;
  }

  _chats(snapshot) {
    const requests = new Map(snapshot.engine_requests.map((r) => [r.request_id, r]));
    const chats = snapshot.runs.map((run) => this._chat(run.run_id, run, requests.get(run.request_id) || null));
    const claimed = new Set(snapshot.runs.map((r) => r.request_id));
    for (const r of snapshot.engine_requests) if (!claimed.has(r.request_id)) chats.push(this._chat(`${r.host}:${r.request_id}`, null, r));
    return chats.sort((a, b) => Number(b.done) - Number(a.done));
  }

  _chat(key, run, request) {
    if (!this.colors.has(key)) this.colors.set(key, LIVE_CHAT_COLORS[this.nextColor++ % LIVE_CHAT_COLORS.length]);
    const done = run ? run.done : request.phase === "done";
    const tps = request?.phase === "decode" ? request.tokens_per_second : null;
    return { key, run, request, done, tps, color: this.colors.get(key), busy: new Set(), pulsed: new Set(), worst: null };
  }

  /* Marks `id` for `chat`: busy for its arrows, and a candidate for the node's label (the slowest chat wins). */
  _touch(chat, id, patch) {
    const pulsed = patch.count !== undefined && patch.count > (this.counts.get(`${chat.key}:${id}`) ?? 0);
    if (patch.count !== undefined) this.counts.set(`${chat.key}:${id}`, patch.count);
    if (pulsed) {
      this.recentUntil.set(`${chat.key}:${id}`, this.now + LIVE_RECENT_MS);
      chat.pulsed.add(id);
    }
    if (patch.active || (this.recentUntil.get(`${chat.key}:${id}`) || 0) > this.now) chat.busy.add(id);
    const node = this._node(id);
    if (patch.active) node.chats.add(chat.key);
    if (!chat.done) node.past = false;
    const candidate = { active: Boolean(patch.active), ratio: patch.ratio || 0, elapsed: patch.elapsed || 0 };
    if (patch.text !== undefined && (!node.best || liveBetter(candidate, node.best))) {
      node.best = candidate;
      Object.assign(node, { text: patch.text, ratio: candidate.ratio, share: patch.share ?? null });
    }
    if (this.groupOf(id) && (patch.active || candidate.ratio) && (!chat.worst || liveBetter(candidate, chat.worst))) {
      chat.worst = { ...candidate, id, text: patch.text };
    }
  }

  _node(id) {
    if (!this.nodes.has(id)) this.nodes.set(id, { chats: new Set(), best: null, past: true, text: "", ratio: 0, share: null });
    return this.nodes.get(id);
  }

  /* Large cluster: running chats sent only as counts (workflow_live_summary.py) -> Map(node id -> count). A folded
  group shows its busiest step's count. */
  _crowdCounts(crowd) {
    const counts = new Map();
    if (!crowd) return counts;
    const add = (id, n) => counts.set(id, (counts.get(id) || 0) + n);
    for (const [phase, c] of Object.entries(crowd.engine)) {
      for (const id of [...(LIVE_PHASE_NODES[phase] || []), "ml_engine_server"]) add(id, c.replies);
    }
    for (const [id, n] of Object.entries(crowd.app)) {
      add(id, n);
      const group = this.groupOf(id);
      if (group) counts.set(group, Math.max(counts.get(group) || 0, n));
    }
    return counts;
  }

  _applyRun(chat, usualMs) {
    const run = chat.run;
    for (const [id, t] of Object.entries(run.nodes)) {
      const unit = LIVE_COUNT_NODES[id];
      const time = t.elapsed_ms > 0 || t.active ? liveFormatMs(t.elapsed_ms) : "";
      const text = unit ? `${id === "broadcast_publish" ? run.chunks : t.count} ${unit}` : time;
      const ratio = !unit && usualMs[id] ? t.elapsed_ms / usualMs[id] : 0;
      this._touch(chat, id, { active: t.active, count: t.count, text, ratio, elapsed: t.elapsed_ms });
    }
  }

  _applyEngine(chat, r) {
    const running = r.phase !== "done";
    const patches = new Map(liveEngineTexts(r));
    if (running) patches.set("ml_engine_server", r.phase === "queued" ? { text: "waiting for a slot" } : {});
    const active = new Set(running ? [...liveEngineNodes(r), "ml_engine_server"] : []);
    for (const id of new Set([...active, ...patches.keys()])) this._touch(chat, id, { active: active.has(id), ...patches.get(id) });
    // Progress counters (no activity of their own): a new token or prefill piece sends a dot down the chain.
    for (const id of ["ml_sampler", "ml_detok", "ml_ndjson"]) this._touch(chat, id, { count: r.generated_tokens });
    this._touch(chat, "ml_embed", { count: r.prefilled_tokens + r.generated_tokens });
  }

  /* The folded "App steps" node: busy when any step inside is, labelled with the slowest one. */
  _applyGroups(chat) {
    const groups = new Set([...chat.busy].map((id) => this.groupOf(id)).filter(Boolean));
    for (const group of groups) {
      const worst = chat.worst;
      const label = worst && WORKFLOW_NODES.find((n) => n.id === worst.id)?.label.split("\n")[0];
      const text = label ? `${label}${worst.text ? ` ${worst.text}` : ""}` : "";
      this._touch(chat, group, { active: true, text, ratio: worst?.ratio || 0, elapsed: worst?.elapsed || 0 });
    }
  }

  /* Per arrow: the chats busy at both ends, combined tokens/s, and a dot per chat that just finished the start. */
  _edges(chats, crowd, crowdSnapshot) {
    const out = new Map();
    const decode = new Set(LIVE_PHASE_NODES.decode);
    for (const edge of this.edges) {
      const users = chats.filter((c) => c.busy.has(edge.from) && c.busy.has(edge.to));
      // Counted chats: as many as the less busy end (they are not followed one by one).
      const extra = Math.min(crowd.get(edge.from) || 0, crowd.get(edge.to) || 0);
      if (!users.length && !extra) continue;
      const crowdTps = extra && decode.has(edge.from) && decode.has(edge.to) ? crowdSnapshot.engine.decode?.tokens_per_second || 0 : 0;
      const tps = users.reduce((sum, c) => sum + (c.tps || 0), crowdTps);
      out.set(`${edge.from}>${edge.to}`, {
        count: users.length + extra,
        speed: tps ? Math.min(Math.max(tps / LIVE_BASE_TPS, 0.4), 4) : 1,
        dots: users.filter((c) => c.pulsed.has(edge.from)).map((c) => c.color),
      });
    }
    return out;
  }
}

/* Running and highest ratio first, then the longest. */
function liveBetter(a, b) {
  if (a.active !== b.active) return a.active;
  if (a.ratio !== b.ratio) return a.ratio > b.ratio;
  return a.elapsed > b.elapsed;
}
