/* Settings > Matricxon > API key (app/templates/_matricxon_api_key.html): sets or removes the key pAIring sends to
Matricxon, via /api/settings/matricxon/api-key. The key is never read back, only whether one is set. Uses api from
app.js. */
class MatricxonApiKeyPanel {
  static URL = "/api/settings/matricxon/api-key";

  constructor(root) {
    this.current = root.querySelector("#matricxon-api-key-current");
    this.input = root.querySelector("#matricxon-api-key-input");
    this.where = root.querySelector("#matricxon-api-key-where");
    this.saveButton = root.querySelector("#matricxon-api-key-save");
    this.removeButton = root.querySelector("#matricxon-api-key-remove");
    this.restartButton = root.querySelector("#matricxon-api-key-restart");
    this.status = root.querySelector("#matricxon-api-key-status");
    root.querySelector("#matricxon-api-key-generate").addEventListener("click", () => this.generate());
    this.saveButton.addEventListener("click", () => this.save(this.input.value.trim()));
    this.removeButton.addEventListener("click", () => this.remove());
    this.restartButton.addEventListener("click", () => this.restart());
  }

  /** 32 random bytes as hex: long enough that guessing is hopeless. */
  generate() {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    this.input.type = "text";
    this.input.value = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  show(state) {
    this.current.textContent = state.set ? "A key is set: pAIring sends it on every Matricxon call." : "No key: Matricxon answers anyone who can reach it.";
    this.removeButton.classList.toggle("hidden", !state.set);
    this.where.textContent = state.local
      ? "Local Matricxon: the key is saved in its .env, so it checks the key from its next start. Other cluster nodes need MATRICXON_API_KEYS set to the same key."
      : "Remote Matricxon: set MATRICXON_API_KEYS to the same key on each Matricxon server, then restart it.";
    this.restartButton.classList.toggle("hidden", !state.restart_needed);
    this.status.textContent = state.restart_needed ? "Saved. Restart Matricxon to apply it (running replies stop)." : "";
  }

  async run(request, doneText) {
    this.saveButton.disabled = this.removeButton.disabled = true;
    try {
      this.show(await request());
      if (doneText && !this.status.textContent) this.status.textContent = doneText;
    } catch (error) {
      this.status.textContent = error.message;
    } finally {
      this.saveButton.disabled = this.removeButton.disabled = false;
    }
  }

  load() {
    return this.run(() => api(MatricxonApiKeyPanel.URL));
  }

  save(key) {
    if (!key) {
      this.status.textContent = "Type a key, or press Generate.";
      return;
    }
    return this.run(async () => {
      const state = await api(MatricxonApiKeyPanel.URL, { method: "PUT", body: JSON.stringify({ key }) });
      this.input.value = "";
      this.input.type = "password";
      return state;
    }, "Saved");
  }

  remove() {
    if (!confirm("Remove the API key? Anyone who can reach Matricxon will be able to use it.")) return;
    return this.run(() => api(MatricxonApiKeyPanel.URL, { method: "PUT", body: JSON.stringify({ key: "" }) }), "Removed");
  }

  async restart() {
    if (!confirm("Restart Matricxon now? Replies in progress stop.")) return;
    this.restartButton.disabled = true;
    this.status.textContent = "Restarting…";
    try {
      await api("/api/settings/matricxon/stop", { method: "POST" });
      await api("/api/settings/matricxon/start", { method: "POST" });
      this.restartButton.classList.add("hidden");
      this.status.textContent = "Restarted: Matricxon now checks the key.";
    } catch (error) {
      this.status.textContent = error.message;
    } finally {
      this.restartButton.disabled = false;
    }
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const root = document.getElementById("matricxon-api-key-panel");
  if (!root) return;
  const { active_engine: activeEngine } = await api("/health");
  if (activeEngine !== "matricxon") return;
  root.classList.remove("hidden");
  new MatricxonApiKeyPanel(root).load();
});
