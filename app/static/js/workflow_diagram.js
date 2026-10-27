/*
 * D3 rendering for the Stats "Visual chat workflow": the chat model's inference stages as a left-to-right chart in
 * three lanes (layout: workflow_diagram_inference.js), and every other step as a card below it
 * (workflow_diagram_cards.js). Content: workflow_diagram_data.js / workflow_diagram_ml.js. Invoked lazily via
 * initWorkflowDiagram, called once by stats.js on first open. Node positions are fixed, not a force simulation.
 */

const WORKFLOW_ARROW_MARKER_ID = "wf-arrow";

class InferenceChart {
  static ARC_Y = 46; // the decode loop's arrow runs over the top at this height
  static PORT_GAP = 16; // arrows entering the same side of a node land this far apart
  static FLOW_INSET = 12; // live streams stop where the arrowhead starts
  static BORDER = "#d5dbe7"; // node border, as the helpdesk's; the picked node's turns its layer colour
  static TEXT_X = 48; // labels start right of the icon
  static BADGE_TITLES = {
    K: "Runs on native C kernels",
    G: "Can run on the GPU (experimental, MATRICXON_DEVICE=cuda or mps)",
    "K|G": "Runs on native C kernels on the CPU, or on the GPU (experimental) when the engine is set to use one",
    MCP: "MCP stage: only runs when the chat has Tools turned on",
  };

  constructor(svg) {
    this.svg = svg;
    this.nodes = inferenceNodes();
    this.byId = new Map(this.nodes.map((n) => [n.id, n]));
    this.ports = this._ports();
  }

  /* The side of `edge.to` an arrow enters: left/right for neighbouring columns, top/bottom within one. */
  _endSide(edge) {
    const [a, b] = [this.byId.get(edge.from), this.byId.get(edge.to)];
    if (a.x === b.x) return b.y > a.y ? "top" : "bottom";
    return b.x > a.x ? "left" : "right";
  }

  /* Arrows sharing a node side get their own spot on it (ordered by where they come from, so they never cross). */
  _ports() {
    const sides = new Map();
    for (const edge of INFERENCE_EDGES.filter((e) => !e.arc && !e.exit)) {
      const key = `${edge.to}:${this._endSide(edge)}`;
      sides.set(key, [...(sides.get(key) || []), edge]);
    }
    const ports = new Map();
    for (const [key, edges] of sides) {
      const across = key.endsWith("left") || key.endsWith("right") ? "y" : "x";
      edges.sort((p, q) => this.byId.get(p.from)[across] - this.byId.get(q.from)[across]);
      edges.forEach((edge, i) => ports.set(edge, (i - (edges.length - 1) / 2) * InferenceChart.PORT_GAP));
    }
    return ports;
  }

  draw() {
    const { w, h, col, row, left, top } = INFERENCE_SIZE;
    const cols = Math.max(...Object.values(INFERENCE_LAYOUT).map(([c]) => c)) + 1;
    const rows = Math.max(...Object.values(INFERENCE_LAYOUT).map(([, r]) => r)) + 1;
    const width = left * 2 + (cols - 1) * col + w;
    const height = top + (rows - 1) * row + h + 40; // room for the layer frame's caption
    this.height = height;
    // Never drawn smaller than 1:1 (shrunk text blurs); wider boards scale it up, narrower ones scroll sideways.
    this.svg.attr("viewBox", `0 0 ${width} ${height}`).style("width", "100%").style("height", "auto")
      .style("min-width", `${width}px`).style("max-width", `${Math.round(width * 1.25)}px`);
    this._marker();
    const root = this.svg.append("g").attr("class", "wf-root");
    this._lanes(root, height);
    this._edges(root);
    this._nodes(root);
  }

  _marker() {
    this.svg.append("defs").append("marker").attr("id", WORKFLOW_ARROW_MARKER_ID).attr("viewBox", "0 0 10 10")
      .attr("refX", 9).attr("refY", 5).attr("markerWidth", 7).attr("markerHeight", 7)
      .attr("orient", "auto-start-reverse").append("path").attr("d", "M0,1 L9,5 L0,9 Z").attr("class", "wf-arrow");
    this.svg.select("defs").append("filter").attr("id", "wf-shadow").attr("x", "-20%").attr("y", "-20%")
      .attr("width", "140%").attr("height", "160%").append("feDropShadow").attr("dx", 0).attr("dy", 2)
      .attr("stdDeviation", 3).attr("flood-opacity", 0.12);
  }

  _lanes(root, height) {
    const { w, col, left } = INFERENCE_SIZE;
    const lanes = root.append("g").attr("class", "wf-lanes");
    for (const lane of INFERENCE_LANES) {
      const x = left + lane.first * col - 12;
      const width = (lane.last - lane.first) * col + w + 24;
      lanes.append("rect").attr("class", `wf-lane wf-lane-${INFERENCE_LANES.indexOf(lane) % 2}`).attr("x", x).attr("y", 6).attr("width", width)
        .attr("height", height - 12).attr("rx", 16);
      lanes.append("text").attr("class", "wf-lane-title").attr("x", x + width / 2).attr("y", 27)
        .attr("fill", WORKFLOW_CATEGORY_COLORS[lane.group]).text(lane.title.toUpperCase());
    }
    this._layerFrame(lanes);
  }

  /* Dashed frame around the one-layer column, so its steps read as a single layer. */
  _layerFrame(parent) {
    const { w, col, left } = INFERENCE_SIZE;
    const frame = INFERENCE_LAYER_FRAME;
    const column = this.nodes.filter((n) => INFERENCE_LAYOUT[n.id][0] === frame.col);
    const top = Math.min(...column.map((n) => n.y)) - 14;
    const bottom = Math.max(...column.map((n) => n.y + n.h)) + 10;
    const x = left + frame.col * col - 9;
    const color = WORKFLOW_CATEGORY_COLORS[frame.group];
    parent.append("rect").attr("class", "wf-layer-frame").attr("x", x).attr("y", top).attr("width", w + 18)
      .attr("height", bottom - top).attr("rx", 14).attr("stroke", color);
    parent.append("text").attr("class", "wf-layer-caption").attr("x", x + (w + 18) / 2).attr("y", bottom + 15)
      .attr("fill", color).text(frame.caption);
  }

  /* Side to side for neighbouring columns, top/bottom within a column, or over the top for `arc` edges. `inset`
  ends the path that much before the node (the live stream, which must not cover the arrowhead). */
  edgePath(edge, inset = 0) {
    const a = this.byId.get(edge.from);
    const b = this.byId.get(edge.to);
    const port = this.ports.get(edge) || 0;
    const path = d3.path();
    if (edge.exit) {
      // Straight down out of the chart, towards the app steps (cards) below it.
      path.moveTo(a.x + a.w / 2, a.y + a.h);
      path.lineTo(a.x + a.w / 2, this.height - 10 - inset);
      return path.toString();
    }
    if (edge.arc) {
      const [sx, tx, y, r] = [a.x + a.w / 2, b.x + b.w / 2, InferenceChart.ARC_Y, 12];
      const side = Math.sign(tx - sx);
      path.moveTo(sx, a.y);
      path.lineTo(sx, y + r);
      path.quadraticCurveTo(sx, y, sx + side * r, y);
      path.lineTo(tx - side * r, y);
      path.quadraticCurveTo(tx, y, tx, y + r);
      path.lineTo(tx, b.y - inset);
    } else if (a.x === b.x) {
      const down = b.y > a.y;
      const [sy, ey] = [down ? a.y + a.h : a.y, down ? b.y - inset : b.y + b.h + inset];
      const ex = b.x + b.w / 2 + port;
      path.moveTo(a.x + a.w / 2, sy);
      path.bezierCurveTo(a.x + a.w / 2, (sy + ey) / 2, ex, (sy + ey) / 2, ex, ey);
    } else {
      const fwd = b.x > a.x;
      const [sx, ex] = [fwd ? a.x + a.w : a.x, fwd ? b.x - inset : b.x + b.w + inset];
      const [sy, ey] = [a.y + a.h / 2, b.y + b.h / 2 + port];
      path.moveTo(sx, sy);
      path.bezierCurveTo((sx + ex) / 2, sy, (sx + ex) / 2, ey, ex, ey);
    }
    return path.toString();
  }

  /* Helpdesk-style lines: a soft wide wire under a thin dashed line (side paths finer dashes). */
  _edges(root) {
    const wires = root.append("g").attr("class", "wf-wires");
    wires.selectAll("path").data(INFERENCE_EDGES).join("path").attr("class", "wf-wire").attr("d", (d) => this.edgePath(d));
    const g = root.append("g").attr("class", "wf-edges");
    g.selectAll("path").data(INFERENCE_EDGES).join("path")
      .attr("class", (d) => "wf-edge wf-line" + (d.branch ? " wf-edge-branch" : ""))
      .attr("d", (d) => this.edgePath(d))
      .attr("data-flow", (d) => this.edgePath(d, d.noArrow ? 0 : InferenceChart.FLOW_INSET))
      .attr("fill", "none").attr("marker-end", (d) => (d.noArrow ? null : `url(#${WORKFLOW_ARROW_MARKER_ID})`));
    for (const edge of INFERENCE_EDGES.filter((e) => e.label)) {
      const [a, b] = [this.byId.get(edge.from), this.byId.get(edge.to)];
      const width = edge.label.length * 6 + 16;
      // Beside the exit line (left of it, clear of its stream), or on the over-the-top arc between its two ends.
      const [x, y] = edge.exit
        ? [a.x + a.w / 2 - width - 8, (a.y + a.h + this.height) / 2 - 15]
        : [(a.x + b.x + INFERENCE_SIZE.w - width) / 2, InferenceChart.ARC_Y - 10];
      const pill = root.append("g").attr("class", "wf-edge-label").attr("transform", `translate(${x},${y})`);
      pill.append("rect").attr("width", width).attr("height", 20).attr("rx", 10);
      pill.append("text").attr("x", width / 2).attr("y", 14).text(edge.label);
    }
  }

  _nodes(root) {
    const groups = root.append("g").attr("class", "wf-nodes").selectAll("g").data(this.nodes).join("g")
      .attr("class", "wf-node").attr("data-id", (d) => d.id).attr("transform", (d) => `translate(${d.x},${d.y})`)
      .attr("tabindex", 0).attr("role", "button").style("cursor", "pointer")
      .on("click", (_event, d) => showWorkflowDetail(d))
      .on("keydown", (event, d) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), showWorkflowDetail(d)));
    groups.append("title").text((d) => d.label.replace(/\n/g, " "));
    // Helpdesk-style card: white, soft shadow, neutral border, a coloured accent bar and icon in the layer's colour.
    const color = (d) => WORKFLOW_CATEGORY_COLORS[d.category] || "#8b95ad";
    groups.append("rect").attr("class", "wf-body").attr("width", (d) => d.w).attr("height", (d) => d.h).attr("rx", 14)
      .attr("stroke", InferenceChart.BORDER).attr("stroke-width", 1.5).attr("filter", "url(#wf-shadow)");
    groups.append("rect").attr("class", "wf-accent").attr("x", 0).attr("y", 12).attr("width", 5)
      .attr("height", (d) => d.h - 24).attr("rx", 2.5).attr("fill", color);
    groups.append("circle").attr("cx", 27).attr("cy", (d) => d.h / 2).attr("r", 14).attr("fill", color).attr("fill-opacity", 0.14);
    groups.append("g").attr("class", "wf-icon").attr("stroke", color)
      .attr("transform", (d) => `translate(19.5,${d.h / 2 - 7.5}) scale(0.625)`).html((d) => workflowIcon(d));
    groups.each((d, i, nodes) => this._label(d3.select(nodes[i]), d));
    this._badges(groups);
  }

  /* Up to two left-aligned lines; a long line gets a smaller font down to a readable size, then a trailing "…". */
  _label(group, d) {
    const lines = (INFERENCE_LABELS[d.id] || d.label).split("\n").slice(0, 2);
    const max = d.w - InferenceChart.TEXT_X - 8;
    lines.forEach((line, i) => {
      const text = group.append("text").attr("class", i ? "wf-label-sub" : "wf-label").attr("x", InferenceChart.TEXT_X)
        .attr("y", lines.length > 1 ? 22 + i * 15 : d.h / 2 + 4).text(line);
      const fits = () => text.node().getComputedTextLength() <= max;
      let size = i ? 10.5 : 12.5;
      while (!fits() && size > (i ? 9.5 : 11.5)) text.style("font-size", `${(size -= 0.5)}px`);
      for (let cut = line.length - 1; !fits() && cut > 4; cut--) text.text(`${line.slice(0, cut).trimEnd()}…`);
    });
  }

  /* Top-right pill: "K" native C kernels, "G" GPU-capable, "K|G" either, "MCP" only with tools on. */
  _badges(groups) {
    const badgeOf = (d) => [d.native ? "K" : "", d.gpu ? "G" : "", d.mcp ? "MCP" : ""].filter(Boolean).join("|");
    const width = (d) => 10 + 7 * badgeOf(d).length;
    const badges = groups.filter((d) => badgeOf(d)).append("g").attr("class", "wf-native-icon")
      .attr("transform", (d) => `translate(${d.w - width(d) - 8}, -9)`);
    badges.append("rect").attr("width", width).attr("height", 17).attr("rx", 8.5).attr("class", "wf-badge");
    badges.append("text").attr("x", (d) => width(d) / 2).attr("y", 12.5).attr("class", "wf-badge-text").text(badgeOf);
    badges.append("title").text((d) => InferenceChart.BADGE_TITLES[badgeOf(d)]);
  }
}

/* Highlights the picked node or card (null: none). */
function workflowSelect(id) {
  d3.selectAll(".wf-node .wf-body").attr("stroke-width", 1.5).attr("stroke", InferenceChart.BORDER);
  if (id) d3.select(`.wf-node[data-id="${id}"] .wf-body`).attr("stroke-width", 2.5)
    .attr("stroke", (d) => WORKFLOW_CATEGORY_COLORS[d.category] || InferenceChart.BORDER);
  window.workflowCards?.select(id);
}

function initWorkflowDiagram() {
  new WorkflowLegend(document.getElementById("workflow-legend")).render();
  new InferenceChart(d3.select("#workflow-svg")).draw();
  window.workflowCards = new WorkflowCards(document.getElementById("workflow-cards"), workflowCardNodes());
}
