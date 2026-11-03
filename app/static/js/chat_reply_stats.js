/* A reply's speed beside its time (Message.stats, services/reply_stats.py): tokens/sec and time to first token. */
class ReplyStatsLine {
  static show(wrapper, stats) {
    const time = wrapper && wrapper.querySelector(".message-time");
    if (!time || !stats) return;
    let line = time.querySelector(".reply-stats");
    if (!line) {
      line = document.createElement("span");
      line.className = "reply-stats";
      time.appendChild(line);
    }
    const parts = [];
    if (stats.tokens_per_second) parts.push(`${stats.tokens_per_second} tok/s`);
    parts.push(`${ReplyStatsLine.seconds(stats.first_token_ms)} to first token`);
    line.textContent = ` · ${parts.join(" · ")}`;
    const tokens = stats.output_tokens ? `${stats.output_tokens} tokens in ` : "";
    const prompt = stats.prompt_tokens ? `, prompt ${stats.prompt_tokens} tokens` : "";
    line.title = `${tokens}${ReplyStatsLine.seconds(stats.total_ms)}${prompt}`;
  }

  static seconds(ms) {
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)}s`;
  }
}
