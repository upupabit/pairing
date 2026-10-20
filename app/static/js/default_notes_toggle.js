/* Notes page > Rule notes: whether saved persona/rules/skill notes are added to new chats/channels (every user). A plain
on/off toggle, not a Save button: flipping it saves at once, and only affects chats/channels started afterward
(note_service.seed_initial_disabled_notes). Uses `api` from app.js. */

class DefaultNotesToggle {
  static URL = "/api/notes/default-notes-enabled";

  constructor(toggleEl, statusEl) {
    this.toggle = toggleEl;
    this.status = statusEl;
    this.toggle.addEventListener("change", () => this.save());
  }

  async load() {
    const { enabled } = await api(DefaultNotesToggle.URL);
    this.toggle.checked = enabled;
  }

  async save() {
    const enabled = this.toggle.checked;
    this.toggle.disabled = true;
    this.status.textContent = "Saving…";
    try {
      await api(DefaultNotesToggle.URL, { method: "PUT", body: JSON.stringify({ enabled }) });
      this.status.textContent = "Saved";
    } catch (err) {
      this.toggle.checked = !enabled;
      this.status.textContent = err.message;
      this.status.classList.add("text-warning-400");
    } finally {
      this.toggle.disabled = false;
      setTimeout(() => {
        this.status.textContent = "";
        this.status.classList.remove("text-warning-400");
      }, 2500);
    }
  }
}

(() => {
  const toggleEl = document.getElementById("default-notes-enabled-toggle");
  if (toggleEl) new DefaultNotesToggle(toggleEl, document.getElementById("default-notes-enabled-status")).load();
})();
