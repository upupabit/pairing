/* Chat header "Reasoning" chip (conversation.params.think: the engines' thinking switch): click switches off/on (off by
default; a chat saved with no value counts as off), saved for this chat
like the Tools switch (chat_tools.js). Shown only when the chat's model can think (GET
/api/settings/model-capabilities reports "thinking"). When the model's switch sits early in the prompt
("thinking_rereads", e.g. Gemma 4), a chat with messages is re-read once after a change, so it asks first, like the
model picker. Uses api from app.js and activeHasMessages from chat.js. */
class ThinkingChip {
  static STATES = {
    on: { label: "Reasoning: on", title: "Reasons before answering (slower, better on hard questions). Click: off" },
    off: { label: "Reasoning: off", title: "Answers right away. Click: reason before answering" },
  };

  constructor(button) {
    this.button = button;
    this.conversationId = null;
    this.params = null;
    this.capabilities = [];
    this.confirmBox = this.buildConfirm();
    button.parentElement.classList.add("relative");
    button.parentElement.appendChild(this.confirmBox);
    button.addEventListener("click", () => this.click());
  }

  buildConfirm() {
    const box = document.createElement("div");
    box.className =
      "hidden absolute right-0 top-full mt-2 z-20 w-80 max-w-[calc(100vw-2rem)] space-y-2 rounded-lg border border-slate-700 bg-slate-900 p-3 text-xs shadow-lg";
    box.innerHTML = `
      <p class="rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1.5 font-medium leading-snug text-red-400">
        This chat already has messages. With this model, changing Reasoning makes it read the whole conversation again
        before its next reply (once). On a long chat this can take minutes, depending on your system.
      </p>
      <div class="flex gap-2">
        <button type="button" data-change class="rounded-md bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-500">Change</button>
        <button type="button" data-cancel class="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800">Cancel</button>
      </div>`;
    box.querySelector("[data-change]").addEventListener("click", () => {
      box.classList.add("hidden");
      this.next();
    });
    box.querySelector("[data-cancel]").addEventListener("click", () => box.classList.add("hidden"));
    return box;
  }

  click() {
    if (this.capabilities.includes("thinking_rereads") && activeHasMessages) {
      this.confirmBox.classList.toggle("hidden");
      return;
    }
    this.next();
  }

  /* Called when a chat opens or its model changes. */
  async sync(conversationId, conversation, canManage) {
    this.conversationId = conversationId;
    this.params = conversation.params || {};
    this.button.disabled = !canManage;
    this.capabilities = [];
    this.confirmBox.classList.add("hidden");
    this.render();
    this.button.classList.add("hidden");
    let capabilities = null;
    try {
      ({ capabilities } = await api(`/api/settings/model-capabilities?model=${encodeURIComponent(conversation.model || "")}`));
    } catch (_err) {
      return;
    }
    if (this.conversationId === conversationId) {
      this.capabilities = capabilities || [];
      this.button.classList.toggle("hidden", !this.capabilities.includes("thinking"));
    }
  }

  hide() {
    this.conversationId = null;
    this.button.classList.add("hidden");
    this.confirmBox.classList.add("hidden");
  }

  get on() {
    return this.params?.think === true && !this.button.classList.contains("hidden");
  }

  render() {
    const think = this.params?.think === true;
    const state = ThinkingChip.STATES[think ? "on" : "off"];
    this.button.textContent = state.label;
    this.button.title = this.button.disabled ? "Only a channel manager can change this" : state.title;
    this.button.classList.toggle("text-brand-500", think);
  }

  async next() {
    const params = { ...this.params, think: this.params?.think !== true };
    const id = this.conversationId;
    try {
      const conversation = await api(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ params }) });
      if (this.conversationId === id) {
        this.params = conversation.params;
        this.render();
      }
    } catch (err) {
      this.button.title = err.message;
    }
  }
}

const thinkingChip = new ThinkingChip(document.getElementById("thinking-chip"));
