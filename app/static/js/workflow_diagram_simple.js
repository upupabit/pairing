/*
 * The "Simple" Stats workflow view (the New one: workflow_diagram.js; admin picks, workflow_view_setting.py).
 * D3 rendering for the Stats "Visual chat workflow" diagram: mechanics only (content: workflow_diagram_data.js
 * WORKFLOW_NODES/WORKFLOW_EDGES). Invoked lazily via initWorkflowDiagram, called once by stats.js on first open.
 * Not a D3 force simulation: node x/y are fixed and hand-laid-out, as this is a fixed pipeline read as documentation.
 * Laid out top-to-bottom and taller than any viewport, so the container (#workflow-canvas-wrap, stats.html) scrolls
 * natively; drag-to-pan/wheel-zoom had no visible affordance.
 */

const WORKFLOW_ARROW_MARKER_ID = "wf-arrow";
const isMlStage = (category) => category.startsWith("ml_");

/* A smooth cubic-bezier path between two nodes' centers, leaving/entering the side that faces the other node (left/right for mostly-horizontal edges, top/bottom for vertical). Every WORKFLOW_EDGES edge is one of the two, so one function covers all. */
function workflowEdgePath(from, to, dir) {
  const x1 = from.x + from.w / 2;
  const y1 = from.y + from.h / 2;
  const x2 = to.x + to.w / 2;
  const y2 = to.y + to.h / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  // `dir` ('h'/'v') overrides the automatic pick for the few edges where it would run through a node.
  const horizontal = dir ? dir === "h" : Math.abs(dx) >= Math.abs(dy);

  let sx, sy, ex, ey;
  if (horizontal) {
    sx = dx >= 0 ? from.x + from.w : from.x;
    sy = y1;
    ex = dx >= 0 ? to.x : to.x + to.w;
    ey = y2;
  } else {
    sx = x1;
    sy = dy >= 0 ? from.y + from.h : from.y;
    ex = x2;
    ey = dy >= 0 ? to.y : to.y + to.h;
  }

  const path = d3.path();
  path.moveTo(sx, sy);
  // A vertical edge running far sideways (ML engine -> Model get_or_load, NDJSON -> publish_chunk) as a curve stays
  // flat and turns down only at the end, so the arrowhead meets the line at an angle. Drawn as drop, run, drop with
  // rounded corners instead, so the last stretch is straight and the arrowhead sits on it.
  if (!horizontal && Math.abs(ex - sx) > 2 * Math.abs(ey - sy)) {
    const mid = (sy + ey) / 2; // the run sits in the middle of the gap between the two rows
    const r = Math.min(10, Math.abs(ey - mid) / 2, Math.abs(mid - sy));
    const side = Math.sign(ex - sx);
    const down = Math.sign(ey - sy);
    path.lineTo(sx, mid - down * r);
    path.quadraticCurveTo(sx, mid, sx + side * r, mid);
    path.lineTo(ex - side * r, mid);
    path.quadraticCurveTo(ex, mid, ex, mid + down * r);
    path.lineTo(ex, ey);
    return path.toString();
  }
  if (horizontal) {
    const cdx = (ex - sx) / 2;
    path.bezierCurveTo(sx + cdx, sy, ex - cdx, ey, ex, ey);
  } else {
    const cdy = (ey - sy) / 2;
    path.bezierCurveTo(sx, sy + cdy, ex, ey - cdy, ex, ey);
  }
  return path.toString();
}

/* Highlights the picked node (null: none); shared detail panel API, like the New view's. */
function workflowSelect(id) {
  d3.selectAll(".wf-node rect").attr("stroke-width", 1.5);
  if (id) d3.select(`.wf-node[data-id="${id}"] rect`).attr("stroke-width", 3);
}

/* The diagram's content bounds from the node positions; the <svg> is sized to exactly this (plus a margin), so the container's scrollbars appear where content overflows instead of the SVG stretching to the available space. */
function workflowCanvasBounds(nodes = WORKFLOW_NODES) {
  const margin = 40;
  const minX = Math.min(...nodes.map((n) => n.x));
  const minY = Math.min(...nodes.map((n) => n.y));
  const maxX = Math.max(...nodes.map((n) => n.x + n.w));
  const maxY = Math.max(...nodes.map((n) => n.y + n.h));
  return {
    width: maxX - minX + margin * 2,
    height: maxY - minY + margin * 2,
    offsetX: margin - minX,
    offsetY: margin - minY,
  };
}

function initWorkflowDiagram() {
  const svg = d3.select("#workflow-svg");
  // Size and position: WorkflowFocus (workflow_diagram_focus.js), which can fold the app steps away.
  const legend = new WorkflowLegend(document.getElementById("workflow-legend"));
  legend.render();

  svg
    .append("defs")
    .append("marker")
    .attr("id", WORKFLOW_ARROW_MARKER_ID)
    .attr("viewBox", "0 0 10 10")
    .attr("refX", 9)
    .attr("refY", 5)
    .attr("markerWidth", 7)
    .attr("markerHeight", 7)
    .attr("orient", "auto-start-reverse")
    .append("path")
    .attr("d", "M0,0 L10,5 L0,10 Z")
    .attr("fill", ThemeColors.get("--color-slate-500"));

  const root = svg.append("g").attr("class", "wf-root");

  const nodesById = new Map(WORKFLOW_NODES.map((n) => [n.id, n]));

  root
    .append("g")
    .attr("class", "wf-edges")
    .selectAll("path")
    .data(WORKFLOW_EDGES)
    .join("path")
    .attr("class", (d) => "wf-edge" + (d.branch ? " wf-edge-branch" : ""))
    .attr("d", (d) => workflowEdgePath(nodesById.get(d.from), nodesById.get(d.to), d.dir))
    .attr("fill", "none")
    .attr("stroke", (d) => ThemeColors.get(d.branch ? "--color-slate-600" : "--color-slate-500"))
    .attr("stroke-width", (d) => (d.branch ? 1.5 : 2))
    .attr("stroke-dasharray", (d) => (d.branch ? "4 3" : null))
    .attr("marker-end", `url(#${WORKFLOW_ARROW_MARKER_ID})`);

  const nodeGroups = root
    .append("g")
    .attr("class", "wf-nodes")
    .selectAll("g")
    .data(WORKFLOW_NODES)
    .join("g")
    .attr("class", "wf-node")
    .attr("data-id", (d) => d.id)
    .attr("transform", (d) => `translate(${d.x},${d.y})`)
    .style("cursor", "pointer")
    .on("click", (_event, d) => showWorkflowDetail(d));

  nodeGroups
    .append("rect")
    .attr("width", (d) => d.w)
    .attr("height", (d) => d.h)
    .attr("rx", 8)
    .attr("fill", ThemeColors.get("--color-slate-900"))
    .attr("stroke", (d) => WORKFLOW_CATEGORY_COLORS[d.category] || ThemeColors.get("--color-slate-500"))
    .attr("stroke-width", 1.5);

  // ML-engine stages get a tint of their group colour, so forward-pass stages read apart.
  nodeGroups
    .filter((d) => isMlStage(d.category))
    .select("rect")
    .attr("fill", (d) => WORKFLOW_CATEGORY_COLORS[d.category])
    .attr("fill-opacity", 0.14)
    .attr("stroke-width", 2);

  // Top-right badge: "MCP" = a stage that runs only when a chat uses MCP tools; "K" = native C kernels (CPU); "G" = can
  // run on the GPU (experimental); "K|G" = either: C kernels on the CPU, or the GPU when the engine runs on one.
  const BADGE_TITLES = {
    K: "Runs on native C kernels",
    G: "Can run on the GPU (experimental, MATRICXON_DEVICE=cuda or mps)",
    "K|G": "Runs on native C kernels on the CPU, or on the GPU (experimental) when the engine is set to use one",
    MCP: "MCP stage: only runs when the chat has Tools turned on",
  };
  const badgeOf = (d) => [d.native ? "K" : "", d.gpu ? "G" : "", d.mcp ? "MCP" : ""].filter(Boolean).join("|");
  // A small pill straddling the node's top-right border, clear of the label text.
  const badges = nodeGroups
    .filter((d) => badgeOf(d))
    .append("g")
    .attr("class", "wf-native-icon")
    .attr("transform", (d) => `translate(${d.w - (10 + 7 * badgeOf(d).length) - 8}, -9)`);
  badges
    .append("rect")
    .attr("width", (d) => 10 + 7 * badgeOf(d).length)
    .attr("height", 17)
    .attr("rx", 8.5)
    .attr("fill", ThemeColors.get("--color-slate-900"))
    .attr("stroke", ThemeColors.get("--color-slate-500"))
    .attr("stroke-width", 1);
  badges
    .append("text")
    .attr("x", (d) => (10 + 7 * badgeOf(d).length) / 2)
    .attr("y", 12.5)
    .attr("text-anchor", "middle")
    .attr("fill", ThemeColors.get("--color-slate-300"))
    .attr("font-size", "11px")
    .attr("font-weight", "500")
    .attr("font-family", "ui-monospace, Menlo, Consolas, monospace")
    .text((d) => badgeOf(d));
  badges.append("title").text((d) => BADGE_TITLES[badgeOf(d)]);

  root
    .append("g")
    .selectAll("text")
    .data(typeof WORKFLOW_ANNOTATIONS === "undefined" ? [] : WORKFLOW_ANNOTATIONS)
    .join("text")
    .attr("class", "wf-annotation")
    .attr("x", (d) => d.x)
    .attr("y", (d) => d.y)
    .attr("fill", (d) => WORKFLOW_CATEGORY_COLORS[d.group])
    .attr("font-size", "11px")
    .attr("font-weight", "700")
    .attr("letter-spacing", "0.06em")
    .text((d) => d.text);

  nodeGroups.each(function (d) {
    const lines = d.label.split("\n");
    const text = d3
      .select(this)
      .append("text")
      .attr("x", d.w / 2)
      .attr("y", d.h / 2 - ((lines.length - 1) * 14) / 2)
      .attr("text-anchor", "middle")
      .attr("fill", ThemeColors.get("--color-slate-200"))
      .attr("font-size", "12px")
      .attr("font-weight", "500");
    lines.forEach((line, i) => {
      text
        .append("tspan")
        .attr("x", d.w / 2)
        .attr("dy", i === 0 ? 0 : 14)
        .text(line);
    });
  });

  window.workflowFocus = new WorkflowFocus(svg, root);
}
