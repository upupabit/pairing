/*
 * Layout of the Stats "Visual chat workflow" inference chart: the chat model's stages inside the ML engine (nodes from
 * workflow_diagram_ml.js, plus the "ML engine" entry and the publish exit from workflow_diagram_data.js), drawn left to
 * right in three lanes by workflow_diagram.js. Every other node shows as a card below the chart
 * (workflow_diagram_cards.js). Load after workflow_diagram_ml.js.
 */

const INFERENCE_SIZE = { w: 176, h: 58, col: 210, row: 88, left: 20, top: 66 };

// [column, row] per node. Column 2 is one transformer layer, top to bottom; column 3 holds what sits beside it.
const INFERENCE_LAYOUT = {
  ml_engine_server: [0, 0],
  ml_load: [0, 1],
  ml_template: [0, 2],
  ml_tokenize: [0, 3],
  ml_decode_loop: [1, 0],
  ml_vision: [1, 1],
  ml_embed: [1, 2],
  ml_prompt_cache: [1, 3],
  ml_norm_attn: [2, 0],
  ml_attention: [2, 1],
  ml_norm_ffn: [2, 2],
  ml_ffn: [2, 3],
  ml_kv: [3, 0],
  ml_linear_attn: [3, 1],
  ml_kernels: [3, 2],
  ml_layer_loop: [3, 3],
  ml_final_norm: [4, 0],
  ml_lm_head: [4, 1],
  ml_sampler: [4, 2],
  ml_stop_check: [4, 3],
  ml_ndjson: [5, 2],
  ml_detok: [5, 3],
  broadcast_publish: [6, 2],
};

// Shorter labels for the chart's narrow nodes (the full label stays in the tooltip, the detail panel and Simple view).
const INFERENCE_LABELS = {
  ml_kv: "KV cache + state\n(grows per token)",
  ml_linear_attn: "Linear attention\n(Mamba-2 / DeltaNet)",
  ml_kernels: "Matmul kernels\n(C / Numba, dequant)",
  ml_detok: "Detokenizer\n(ids → text, streamed)",
  ml_vision: "Vision tower\n(images → embeddings)",
  ml_layer_loop: "Repeat N layers\n(residual stream)",
  ml_template: "Chat template\n(messages → prompt)",
};

// Lanes behind the columns, titled in their stage group's colour.
const INFERENCE_LANES = [
  { title: "① Before the layers", first: 0, last: 1, group: "ml_pre" },
  { title: "② Inside every layer (×N)", first: 2, last: 3, group: "ml_attn" },
  { title: "③ After the layers", first: 4, last: 6, group: "ml_post" },
];

// A dashed frame around the column that is one layer, captioned under it.
const INFERENCE_LAYER_FRAME = { col: 2, caption: "one layer · repeated ×N", group: "ml_attn" };

// The chart's own arrows (the vertical diagram's ML edges, rerouted for this layout). `arc`: drawn over the top;
// `color`: the live stream's colour (default: the start step's layer colour); `exit`: down out of the chart, to a
// step shown as a card (it streams while that step relays the reply);
// `noArrow`: a plain line, where the direction is plain from the layout (side entries into the RMSNorm steps).
// The KV cache and the matmul kernels serve every step, so they have no arrow; their details say where they fit.
const INFERENCE_EDGES = [
  { from: "ml_engine_server", to: "ml_load" },
  { from: "ml_load", to: "ml_template" },
  { from: "ml_template", to: "ml_tokenize" },
  { from: "ml_tokenize", to: "ml_prompt_cache" },
  { from: "ml_prompt_cache", to: "ml_embed" },
  { from: "ml_vision", to: "ml_embed", branch: true },
  { from: "ml_embed", to: "ml_norm_attn", noArrow: true },
  { from: "ml_norm_attn", to: "ml_attention" },
  { from: "ml_norm_attn", to: "ml_linear_attn", branch: true },
  { from: "ml_attention", to: "ml_norm_ffn" },
  { from: "ml_linear_attn", to: "ml_norm_ffn", branch: true, noArrow: true },
  { from: "ml_norm_ffn", to: "ml_ffn" },
  { from: "ml_ffn", to: "ml_layer_loop" },
  { from: "ml_layer_loop", to: "ml_final_norm", noArrow: true },
  { from: "ml_final_norm", to: "ml_lm_head" },
  { from: "ml_lm_head", to: "ml_sampler" },
  { from: "ml_sampler", to: "ml_stop_check" },
  { from: "ml_stop_check", to: "ml_detok" },
  { from: "ml_detok", to: "ml_ndjson" },
  { from: "ml_ndjson", to: "broadcast_publish" },
  { from: "broadcast_publish", to: "relay_back", exit: true, label: "to the chat" },
  { from: "ml_ndjson", to: "ml_decode_loop", branch: true, arc: true, label: "next token", color: "#7dd3fc" },
  { from: "ml_decode_loop", to: "ml_norm_attn", branch: true, noArrow: true },
];

/* The chart's nodes with their pixel positions, in WORKFLOW_NODES order. */
function inferenceNodes() {
  const { w, h, col, row, left, top } = INFERENCE_SIZE;
  return WORKFLOW_NODES.filter((n) => INFERENCE_LAYOUT[n.id]).map((n) => {
    const [c, r] = INFERENCE_LAYOUT[n.id];
    return Object.assign(n, { x: left + c * col, y: top + r * row, w, h });
  });
}

/* The nodes shown as cards: everything not on the chart. */
function workflowCardNodes() {
  return WORKFLOW_NODES.filter((n) => !INFERENCE_LAYOUT[n.id]);
}
