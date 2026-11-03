/* "Use a different repo or branch" (_update_source.html): where pAIring or Matricxon updates from, via
 * /api/settings/update/source/<product>. Every copy of one product's form shows the same saved setting;
 * a save tells the others ("update-source-saved") so update checks can run again. */
class UpdateSourceForm {
  static URL = "/api/settings/update/source";

  constructor(root) {
    this.root = root;
    this.product = root.dataset.updateSource;
    this.field = (name) => root.querySelector(`[data-field="${name}"]`);
    root.querySelector('[data-action="toggle-source"]').addEventListener("click", () => this.field("panel").classList.toggle("hidden"));
    root.querySelector('[data-action="save"]').addEventListener("click", () => this.save({}));
    root.querySelector('[data-action="clear-token"]').addEventListener("click", () => this.save({ clear_token: true }));
    root.querySelector('[data-action="reset"]').addEventListener("click", () => this.reset());
    document.addEventListener("update-source-saved", (event) => event.detail.product === this.product && this.render(event.detail));
    this.load();
  }

  async load() {
    try {
      this.render(await api(`${UpdateSourceForm.URL}/${this.product}`));
    } catch (err) {
      this.field("status").textContent = err.message;
    }
  }

  render(source) {
    // The default shows in the fields; saving it unchanged means "as installed" (services/update_source.py).
    this.field("repo").value = source.repo || source.default_repo;
    this.field("repo").placeholder = source.default_repo;
    this.field("branch").value = source.branch || source.default_branch;
    this.field("branch").placeholder = source.default_branch;
    this.field("token").value = "";
    this.field("token").placeholder = source.has_token ? "saved: leave empty to keep it" : "none";
    this.root.querySelector('[data-action="clear-token"]').classList.toggle("hidden", !source.has_token);
    const where = source.repo ? `${source.repo} · ${source.branch || source.default_branch}${source.has_token ? " · token" : ""}` : "";
    this.field("current").textContent = where ? `Updates from ${where}` : "";
  }

  async save(extra) {
    const body = {
      repo: this.field("repo").value.trim() || null,
      branch: this.field("branch").value.trim() || null,
      token: this.field("token").value.trim() || null,
      ...extra,
    };
    try {
      const saved = await api(`${UpdateSourceForm.URL}/${this.product}`, { method: "PUT", body: JSON.stringify(body) });
      document.dispatchEvent(new CustomEvent("update-source-saved", { detail: saved }));
      this.field("status").textContent = "Saved. The next update uses it.";
    } catch (err) {
      this.field("status").textContent = err.message;
    }
  }

  async reset() {
    if (!confirm("Update as installed again? The repository, branch and token are removed.")) return;
    this.field("repo").value = "";
    await this.save({ clear_token: true });
  }
}

document.querySelectorAll("[data-update-source]").forEach((root) => new UpdateSourceForm(root));
