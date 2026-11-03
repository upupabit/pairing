/* The access token field in Inference engines > Matricxon > "Use a different version or repo"
 * (engines_matricxon.html): saved with that panel's Save, through /api/settings/update/source/<product>/token, the
 * same token the updates use (settings_update_source.js). Never shown again once saved. */
class EngineTokenField {
  static URL = "/api/settings/update/source";

  constructor(root) {
    this.root = root;
    this.product = root.dataset.engineToken;
    this.input = root.querySelector('[data-field="engine-token"]');
    this.removeButton = root.querySelector('[data-action="remove-engine-token"]');
    this.removeButton.addEventListener("click", () => this.send(null));
    root.closest("[data-field=install-source-panel]")
      ?.querySelector('[data-action="save-install-source"]')
      ?.addEventListener("click", () => this.input.value.trim() && this.send(this.input.value.trim()));
    document.addEventListener("update-source-saved", (event) => event.detail.product === this.product && this.render(event.detail));
    this.load();
  }

  async load() {
    try {
      this.render(await api(`${EngineTokenField.URL}/${this.product}`));
    } catch (_err) {
      // The panel works without it; the Update tab shows the same setting.
    }
  }

  render(source) {
    this.input.value = "";
    this.input.placeholder = source.has_token ? "saved: leave empty to keep it" : "none (public repo)";
    this.removeButton.classList.toggle("hidden", !source.has_token);
  }

  async send(token) {
    if (token === null && !confirm("Remove the access token? A private repo can't be downloaded without it.")) return;
    const saved = await api(`${EngineTokenField.URL}/${this.product}/token`, { method: "PUT", body: JSON.stringify({ token }) });
    document.dispatchEvent(new CustomEvent("update-source-saved", { detail: saved }));
  }
}

document.querySelectorAll("[data-engine-token]").forEach((root) => new EngineTokenField(root));
