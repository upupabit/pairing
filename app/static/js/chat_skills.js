/* The chat header's Skills badge and picker (chat.html #skills-badge, #skills-picker): which skills this chat uses,
 * via /api/skills (routers/skills.py). Drawn with the persona/rules icons (chat.js renderPinnedBadges calls render),
 * and locked the same way: only before the first message, and in a channel only for its admins and managers. */
class ChatSkills {
  constructor() {
    this.badge = document.getElementById("skills-badge");
    this.picker = document.getElementById("skills-picker");
    this.field = (name) => this.picker.querySelector(`[data-field="${name}"]`);
    this.conversationId = null;
    this.chosen = [];
    this.available = [];
    this.selected = new Set();
    this.editable = false;
    this.reason = "";
    this.badge.addEventListener("click", () => this.open());
    this.picker.querySelector('[data-action="close"]').addEventListener("click", () => this.close());
    this.picker.querySelector('[data-action="save"]').addEventListener("click", () => this.save());
    this.field("search").addEventListener("input", () => this.renderList());
    this.field("list").addEventListener("change", (event) => this.onToggle(event));
    this.field("chosen").addEventListener("click", (event) => this.onRemove(event));
    document.addEventListener("keydown", (event) => event.key === "Escape" && this.close());
  }

  /* Called on every redraw of the note icons: loads this chat's skills when the chat changed. */
  async render(conversationId, editable) {
    if (!conversationId) {
      this.badge.classList.add("hidden");
      this.close();
      return;
    }
    if (conversationId !== this.conversationId) {
      this.conversationId = conversationId;
      this.close();
      await this.load();
    }
    if (conversationId !== activeConversationId) return; // switched again meanwhile
    this.editable = editable && this.serverEditable;
    this.drawBadge();
  }

  async load() {
    const conversationId = this.conversationId;
    try {
      const result = await api(`/api/skills/conversation/${conversationId}`);
      if (conversationId !== this.conversationId) return;
      this.chosen = result.chosen;
      this.serverEditable = result.editable;
      this.reason = result.reason || "";
    } catch (_err) {
      this.chosen = [];
      this.serverEditable = false;
    }
  }

  drawBadge() {
    const count = this.chosen.length;
    this.badge.classList.remove("hidden");
    this.badge.textContent = count ? `🛠️ ${count}` : "🛠️";
    // Not faded, like the note badges (chat.js renderPinnedBadges); still opens when locked, to show why.
    this.badge.className = "rounded-full bg-slate-800 px-1.5 py-0.5 transition-colors hover:bg-slate-700";
    const names = count ? this.chosen.map((s) => s.name).join(", ") : "none";
    const locked = activeHasMessages ? " — locked: can only change before the first message" : this.reason ? ` — ${this.reason}` : "";
    this.badge.title = `Skills: ${names}${this.editable ? "" : locked}`;
  }

  async open() {
    closeHeaderPopups("skills");
    this.selected = new Set(this.chosen.map((s) => s.id));
    // Started chat: the red box (as the model picker's warning); otherwise the reason, e.g. a channel member.
    const started = activeHasMessages;
    this.field("locked").classList.toggle("hidden", !started);
    this.field("note").textContent = this.editable || started ? "" : this.reason;
    this.field("search").classList.toggle("hidden", !this.editable);
    this.picker.querySelector('[data-action="save"]').classList.toggle("hidden", !this.editable);
    this.field("status").textContent = "";
    this.picker.classList.remove("hidden");
    if (this.editable) {
      try {
        this.available = await api(`/api/skills/available?conversation_id=${encodeURIComponent(this.conversationId)}`);
      } catch (err) {
        this.field("status").textContent = err.message;
        this.available = [];
      }
    }
    this.renderChosen();
    this.renderList();
    if (this.editable) this.field("search").focus();
  }

  close() {
    this.picker.classList.add("hidden");
  }

  renderChosen() {
    const byId = Object.fromEntries([...this.chosen, ...this.available].map((s) => [s.id, s]));
    const chips = [...this.selected].map((id) => byId[id]).filter(Boolean);
    this.field("chosen").innerHTML = chips.length
      ? chips
          .map(
            (s) => `<span class="inline-flex items-center gap-1 rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-200">${escapeHtml(s.name)}${
              this.editable ? `<button type="button" data-remove="${escapeHtml(s.id)}" class="text-slate-500 hover:text-slate-200" title="Remove">×</button>` : ""
            }</span>`,
          )
          .join("")
      : `<span class="text-xs text-slate-500">${this.editable ? "No skills for this chat yet." : "This chat uses no skills."}</span>`;
  }

  renderList() {
    const list = this.field("list");
    list.classList.toggle("hidden", !this.editable);
    if (!this.editable) return;
    const words = this.field("search").value.toLowerCase().split(/\s+/).filter(Boolean);
    // Name matches first, like the gallery's search (services/skill_templates.py).
    const rank = (s) => (words.every((w) => s.name.toLowerCase().includes(w)) ? 0 : 1);
    const matches = this.available
      .filter((s) => words.every((w) => `${s.name} ${s.description} ${s.category}`.toLowerCase().includes(w)))
      .sort((a, b) => rank(a) - rank(b));
    if (!matches.length) {
      list.innerHTML = `<p class="px-2 py-3 text-xs text-slate-500">${
        this.available.length ? "No skill matches." : "No skills yet: an admin adds them under Admin settings → Skills, and you can write your own under Settings → Skills."
      }</p>`;
      return;
    }
    const groups = {};
    for (const skill of matches) (groups[skill.category] ||= []).push(skill);
    list.innerHTML = Object.entries(groups)
      .map(
        ([category, skills]) => `<p class="px-2 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">${escapeHtml(category)}</p>${skills
          .map(
            (s) => `<label class="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-800">
              <input type="checkbox" data-skill="${escapeHtml(s.id)}" ${this.selected.has(s.id) ? "checked" : ""} class="mt-0.5 accent-brand-500">
              <span class="min-w-0"><span class="text-sm text-slate-200">${escapeHtml(s.name)}</span>${
                s.private ? ' <span class="rounded-full border border-slate-700 px-1.5 text-[10px] text-slate-400">yours</span>' : ""
              }<span class="block text-xs text-slate-500">${escapeHtml(s.description)}</span></span>
            </label>`,
          )
          .join("")}`,
      )
      .join("");
  }

  onToggle(event) {
    const id = event.target.dataset.skill;
    if (!id) return;
    if (event.target.checked) this.selected.add(id);
    else this.selected.delete(id);
    this.renderChosen();
  }

  onRemove(event) {
    const id = event.target.closest("[data-remove]")?.dataset.remove;
    if (!id) return;
    this.selected.delete(id);
    this.renderChosen();
    this.renderList();
  }

  async save() {
    try {
      const result = await api(`/api/skills/conversation/${this.conversationId}`, {
        method: "PUT",
        body: JSON.stringify({ skill_ids: [...this.selected] }),
      });
      this.chosen = result.chosen;
      this.drawBadge();
      this.close();
    } catch (err) {
      this.field("status").textContent = err.message;
    }
  }
}

const chatSkills = new ChatSkills();
