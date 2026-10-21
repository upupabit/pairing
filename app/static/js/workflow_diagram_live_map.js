/*
 * Live workflow view: which diagram nodes a Matricxon reply lights up (phase, stage shares, labels) and the status-box
 * summary of one chat. Used by workflow_diagram_live_state.js; load before it.
 */

const LIVE_FORWARD = ["ml_embed", "ml_layer_loop", "ml_norm_attn", "ml_attention", "ml_norm_ffn", "ml_ffn", "ml_kernels", "ml_kv"];
const LIVE_PHASE_NODES = {
  loading: ["ml_load"],
  building: ["ml_template", "ml_tokenize"],
  queued: [],
  prefill: ["ml_prompt_cache", ...LIVE_FORWARD],
  decode: [...LIVE_FORWARD, "ml_decode_loop", "ml_final_norm", "ml_lm_head", "ml_sampler", "ml_stop_check", "ml_detok", "ml_ndjson"],
};
const LIVE_PHASE_TEXT = {
  loading: "Loading the model",
  building: "Tokenizing the prompt",
  queued: "Waiting for a free model slot",
  prefill: "Reading the prompt",
  decode: "Writing the reply",
  done: "Done",
};
// Matricxon stage groups (StageProfiler.GROUPS) shown as a share of engine time.
const LIVE_STAGE_NODES = {
  embed: ["ml_embed"],
  norm: ["ml_norm_attn", "ml_norm_ffn"],
  attention: ["ml_attention"],
  linear_attention: ["ml_linear_attn"],
  ffn: ["ml_ffn"],
  lm_head: ["ml_lm_head"],
  sampler: ["ml_sampler"],
};
// The chat's current step for the status box: the first active node in this order.
const LIVE_STAGE_PRIORITY = [
  "mcp_server_call", "rag_rerank", "rag_embed", "rag_rank", "rag_retrieve", "chat_prompt_service",
  "chat_service_build", "inference_client_stream", "run_generation_task",
];
const LIVE_COUNT_NODES = { broadcast_publish: "chunks", relay_back: "sent", mcp_record: "tool calls" };

function liveEngineNodes(r) {
  const nodes = [...(LIVE_PHASE_NODES[r.phase] || [])];
  const stages = r.stage_seconds || {};
  if (stages.linear_attention > 0) {
    nodes.push("ml_linear_attn");
    if (!stages.attention) nodes.splice(nodes.indexOf("ml_attention"), 1);
  }
  return nodes;
}

/* [id, {text, ratio?, share?}] labels for one reply's engine nodes. */
function liveEngineTexts(r) {
  const out = [];
  if (r.load_seconds > 0.05) out.push(["ml_load", { text: liveFormatMs(r.load_seconds * 1000), elapsed: r.load_seconds * 1000 }]);
  if (r.prompt_tokens) out.push(["ml_prompt_cache", { text: `${r.reused_tokens}/${r.prompt_tokens} reused` }]);
  out.push(["ml_layer_loop", { text: liveLayerText(r), ratio: liveRateRatio(r) }]);
  if (r.tokens_per_second) {
    const ratio = r.usual_tokens_per_second ? r.usual_tokens_per_second / r.tokens_per_second : 0;
    out.push(["ml_decode_loop", { text: `${r.tokens_per_second.toFixed(1)} tok/s`, ratio }]);
  }
  const stages = r.stage_seconds || {};
  const total = Object.entries(stages).reduce((sum, [group, s]) => (group === "matmul" ? sum : sum + s), 0);
  if (total <= 0) return out;
  for (const [group, ids] of Object.entries(LIVE_STAGE_NODES)) {
    const share = (stages[group] || 0) / total;
    if (share <= 0) continue;
    const pct = share < 0.01 ? "<1%" : `${Math.round(share * 100)}%`;
    for (const id of ids) out.push([id, { share, text: group === "norm" ? `norms ${pct}` : pct }]);
  }
  const matmul = Math.min((stages.matmul || 0) / total, 1);
  out.push(["ml_kernels", { share: matmul, text: `${Math.round(matmul * 100)}% matmul` }]);
  return out;
}

function liveLayerText(r) {
  // The count moves once per 256-token piece (a minute or more on a slow CPU); the layer shows it is moving.
  if (r.phase === "prefill") {
    const layer = r.layer ? ` · layer ${r.layer}/${r.layer_count}` : "";
    return `prefill ${r.prefilled_tokens}/${r.prompt_tokens - r.reused_tokens}${layer}`;
  }
  if (r.phase === "decode" && r.layer) return `layer ${r.layer}/${r.layer_count} · tok ${r.generated_tokens}`;
  return r.first_token_seconds != null ? `first token ${liveFormatMs(r.first_token_seconds * 1000)}` : "";
}

/* Prefill speed against this model's usual, once the first token is out. */
function liveRateRatio(r) {
  const fresh = r.prompt_tokens - r.reused_tokens;
  if (!r.usual_prefill_tokens_per_second || !r.first_token_seconds || fresh <= 32) return 0;
  return r.usual_prefill_tokens_per_second / (fresh / r.first_token_seconds);
}

/* One status-box row. `untracked`: a Matricxon reply no pAIring chat here started (a smart title, another instance). */
function liveChatSummary(chat) {
  const { run, request: r } = chat;
  let step = LIVE_PHASE_TEXT.done;
  if (!chat.done) {
    const appNode = run && LIVE_STAGE_PRIORITY.find((id) => run.nodes[id]?.active);
    const engineStep = r && r.phase !== "done" ? LIVE_PHASE_TEXT[r.phase] : null;
    const label = appNode && WORKFLOW_NODES.find((n) => n.id === appNode)?.label.replace(/\n/g, " ");
    const generic = ["inference_client_stream", "run_generation_task"].includes(appNode);
    step = (appNode && !generic ? label : engineStep) || label || "Starting";
  }
  const appFocus = run && Object.keys(run.nodes).find((id) => run.nodes[id].active);
  return {
    key: chat.key,
    color: chat.color,
    untracked: !run,
    model: run ? run.model : r.model,
    done: chat.done,
    step,
    focus: r && r.phase !== "done" ? LIVE_PHASE_NODES[r.phase]?.[0] || "ml_engine_server" : appFocus,
    elapsedMs: run ? run.elapsed_ms : r.elapsed_seconds * 1000,
    ttftMs: r?.first_token_seconds != null ? r.first_token_seconds * 1000 : null,
    ttftLevel: r ? liveLevel(liveRateRatio(r)) : "",
    tps: r?.tokens_per_second ?? null,
    tpsLevel: r?.usual_tokens_per_second && r.tokens_per_second ? liveLevel(r.usual_tokens_per_second / r.tokens_per_second) : "",
    tokens: r?.generated_tokens ?? 0,
    layer: r?.layer ? `${r.layer}/${r.layer_count}` : null,
  };
}
