/* Line icons (24x24, stroke) for the New Stats workflow view: one per inference chart node, one per card layer
(workflow_diagram.js, workflow_diagram_cards.js). A node without one falls back to its layer's icon. */

const WORKFLOW_ICON_PATHS = {
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><path d="M12 15V3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M16 13H8M16 17H8"/>',
  hash: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
  repeat: '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  wave: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  bars: '<path d="M12 20V10M18 20V4M6 20v-4"/>',
  shuffle: '<polyline points="16 3 21 3 21 8"/><path d="M4 20 21 3"/><polyline points="21 16 21 21 16 21"/><path d="m15 15 6 6M4 4l5 5"/>',
  stop: '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><path d="m15 9-6 6M9 9l6 6"/>',
  type: '<polyline points="4 7 4 4 20 4 20 7"/><path d="M9 20h6M12 4v16"/>',
  send: '<path d="M22 2 11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
  radio: '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48 0a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  route: '<circle cx="6" cy="19" r="3"/><circle cx="18" cy="5" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
};

const WORKFLOW_NODE_ICONS = {
  ml_engine_server: "server", ml_load: "download", ml_template: "file", ml_tokenize: "hash",
  ml_prompt_cache: "database", ml_decode_loop: "repeat", ml_vision: "image", ml_embed: "grid",
  ml_norm_attn: "sliders", ml_norm_ffn: "sliders", ml_final_norm: "sliders", ml_attention: "eye",
  ml_linear_attn: "wave", ml_ffn: "zap", ml_kv: "database", ml_kernels: "cpu", ml_layer_loop: "layers",
  ml_lm_head: "bars", ml_sampler: "shuffle", ml_stop_check: "stop", ml_detok: "type", ml_ndjson: "send",
  broadcast_publish: "radio",
};

const WORKFLOW_CATEGORY_ICONS = {
  frontend: "monitor", router: "route", service: "box", background_task: "clock", engine: "server", broadcast: "radio",
};

/* The icon's SVG paths for a node: its own, else its layer's, else a box. */
function workflowIcon(node) {
  const name = WORKFLOW_NODE_ICONS[node.id] || WORKFLOW_CATEGORY_ICONS[node.category] || (node.category.startsWith("ml_") ? "cpu" : "box");
  return WORKFLOW_ICON_PATHS[name];
}
