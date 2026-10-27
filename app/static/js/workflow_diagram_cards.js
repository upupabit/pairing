/*
 * The Stats "Visual chat workflow" steps that are not on the inference chart (the app side: send, prompt build, RAG,
 * tools, delivery; and the RAG embedding model's stages), as a grid of cards under the chart. Clicking a card opens the
 * same detail panel as a chart node. The live view (workflow_diagram_live.js) lights cards up through update(); it only
 * toggles classes and text, so a busy chat never rebuilds the grid.
 */

class WorkflowCards {
  constructor(el, nodes) {
    this.el = el;
    this.nodes = nodes;
    this.cards = new Map();
    this.el.innerHTML = nodes.map((n) => this._html(n)).join("");
    for (const card of this.el.querySelectorAll("[data-id]")) {
      const node = nodes.find((n) => n.id === card.dataset.id);
      this.cards.set(node.id, { el: card, metric: card.querySelector(".wf-card-metric"), tag: card.querySelector(".wf-card-tag"), text: "", tagText: "" });
      card.addEventListener("click", () => showWorkflowDetail(node));
    }
    const count = document.getElementById("workflow-cards-count");
    if (count) count.textContent = String(nodes.length);
  }

  _html(n) {
    const [title, ...rest] = n.label.split("\n");
    const color = WORKFLOW_CATEGORY_COLORS[n.category] || "";
    const layer = formatCategoryLabel(WORKFLOW_CATEGORY_LABELS[n.category] || n.category);
    return `<button type="button" class="wf-card" data-id="${escapeHtml(n.id)}" data-category="${escapeHtml(n.category)}"
      style="--wf-color:${color}" title="${escapeHtml(n.detail.title)}">
      <span class="wf-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true">${workflowIcon(n)}</svg></span>
      <span class="wf-card-layer">${layer}</span>
      <span class="wf-card-title">${WorkflowCards.breakable(title)}</span>
      <span class="wf-card-sub">${escapeHtml(rest.join(" "))}</span>
      <span class="wf-card-foot"><span class="wf-card-server">${escapeHtml(n.detail.server)}</span>
        <span class="wf-card-tag"></span><span class="wf-card-metric"></span></span>
    </button>`;
  }

  /* Escaped text that wraps after . _ / or between camelCase words in long code names, never mid-word. */
  static breakable(text) {
    return escapeHtml(text).replace(/([._/])/g, "$1<wbr>").replace(/([a-z])([A-Z])/g, "$1<wbr>$2");
  }

  /* `states`: Map(node id -> live node state, workflow_diagram_live_state.js), empty when not live. */
  update(states) {
    for (const [id, card] of this.cards) {
      const state = states.get(id);
      const level = state ? liveLevel(state.ratio) : "";
      const cls = card.el.classList;
      cls.toggle("wf-card-active", Boolean(state?.active));
      cls.toggle("wf-card-past", Boolean(state?.past));
      cls.toggle("wf-card-warn", level === "warn");
      cls.toggle("wf-card-crit", level === "crit");
      this._text(card, "metric", "text", state?.text || "");
      this._text(card, "tag", "tagText", level ? `${state.ratio.toFixed(1)}× usual` : "");
    }
  }

  _text(card, el, key, value) {
    if (card[key] === value) return; // unchanged text is not touched, so no restyle
    card[key] = value;
    card[el].textContent = value;
  }

  select(id) {
    for (const [cardId, card] of this.cards) card.el.classList.toggle("wf-card-selected", cardId === id);
  }

  /* Legend filter: fades the cards outside `category` (null: show all). */
  fade(category, faded) {
    for (const card of this.cards.values()) card.el.style.opacity = !category || card.el.dataset.category === category ? "" : faded;
  }
}
