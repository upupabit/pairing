/* Settings > Matricxon > API key (app/templates/_matricxon_api_key.html), and the Cluster page's API key card
(app/templates/_cluster_api_key_form.html): sets or removes the key pAIring sends to Matricxon. Each server gets it at
once. The key is never read back, only whether one is set. Uses api from app.js. */
class MatricxonApiKeyPanel {
  constructor(root, saveUrl) {
    this.saveUrl = saveUrl;
    this.current = root.querySelector("[data-key-current]");
    this.input = root.querySelector("[data-key-input]");
    this.saveButton = root.querySelector("[data-key-save]");
    this.removeButton = root.querySelector("[data-key-remove]");
    this.status = root.querySelector("[data-key-status]");
    root.querySelector("[data-key-generate]").addEventListener("click", () => this.generate());
    this.saveButton.addEventListener("click", () => this.save(this.input.value.trim()));
    this.removeButton.addEventListener("click", () => this.remove());
  }

  /** 32 random bytes as hex: long enough that guessing is hopeless. */
  generate() {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    this.input.type = "text";
    this.input.value = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  show(state) {
    this.current.textContent = state.set
      ? "A key is set: Matricxon serves only callers that send it, and pAIring always does."
      : "No key: Matricxon answers anyone who can reach it.";
    this.removeButton.classList.toggle("hidden", !state.set);
  }

  async run(request, doneText) {
    this.saveButton.disabled = this.removeButton.disabled = true;
    this.status.textContent = doneText ? "Sending to every Matricxon…" : "";
    try {
      this.show(await request());
      this.status.textContent = doneText || "";
    } catch (error) {
      this.status.textContent = error.message;
    } finally {
      this.saveButton.disabled = this.removeButton.disabled = false;
    }
  }

  load() {
    return this.run(() => api("/api/settings/matricxon/api-key"));
  }

  save(key) {
    if (!key) {
      this.status.textContent = "Type a key, or press Generate.";
      return;
    }
    return this.run(async () => {
      const state = await api(this.saveUrl, { method: "PUT", body: JSON.stringify({ key }) });
      this.input.value = "";
      this.input.type = "password";
      return state;
    }, "Saved on every Matricxon.");
  }

  remove() {
    if (!confirm("Remove the API key? Anyone who can reach Matricxon will be able to use it.")) return;
    return this.run(() => api(this.saveUrl, { method: "PUT", body: JSON.stringify({ key: "" }) }), "Removed from every Matricxon.");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const card = document.getElementById("cluster-api-key-form");
  if (card) {
    new MatricxonApiKeyPanel(card, "/api/cluster/api-key").load();
    return;
  }
  const root = document.getElementById("matricxon-api-key-panel");
  if (!root) return;
  const { active_engine: activeEngine } = await api("/health");
  if (activeEngine !== "matricxon") return;
  const state = await api("/api/settings/matricxon/api-key").catch(() => null);
  // settings.js reads the flag when the Active engine picker changes, and shows nothing before it is set.
  root.dataset.clusterOwned = state?.cluster ? "1" : "0";
  if (state?.cluster) {
    root.classList.add("hidden");
    document.getElementById("matricxon-api-key-managed").classList.remove("hidden");
    return;
  }
  root.classList.remove("hidden");
  new MatricxonApiKeyPanel(root, "/api/settings/matricxon/api-key").show(state ?? { set: false });
});
