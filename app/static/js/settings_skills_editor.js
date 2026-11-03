/* The skill form shared by Admin settings > Skills (settings_skills_admin.js) and Settings > Skills
 * (settings_skills_user.js): name, category, description, the instructions, and for the library "enabled". */
class SkillEditor {
  constructor(root, { onSave, withEnabled }) {
    this.root = root;
    this.onSave = onSave;
    this.field = (name) => root.querySelector(`[data-field="${name}"]`);
    this.field("enabled-wrap")?.classList.toggle("hidden", !withEnabled);
    root.querySelector('[data-action="save"]').addEventListener("click", () => this.save());
    root.querySelector('[data-action="cancel"]').addEventListener("click", () => this.close());
    this.editingId = null;
  }

  open(skill = null, categories = []) {
    this.editingId = skill?.id || null;
    this.field("title").textContent = skill ? `Edit "${skill.name}"` : "New skill";
    this.field("name").value = skill?.name || "";
    this.field("category").value = skill?.category || "";
    this.field("description").value = skill?.description || "";
    this.field("content").value = skill?.content || "";
    if (this.field("enabled")) this.field("enabled").checked = skill ? skill.enabled : true;
    this.field("categories").innerHTML = categories.map((c) => `<option value="${escapeHtml(c)}">`).join("");
    this.field("status").textContent = "";
    this.root.classList.remove("hidden");
    this.root.scrollIntoView({ behavior: "smooth", block: "nearest" });
    this.field("name").focus();
  }

  close() {
    this.root.classList.add("hidden");
  }

  async save() {
    const body = {
      name: this.field("name").value.trim(),
      category: this.field("category").value.trim() || "Other",
      description: this.field("description").value.trim(),
      content: this.field("content").value.trim(),
      enabled: this.field("enabled") ? this.field("enabled").checked : true,
    };
    if (!body.name || !body.content) {
      this.field("status").textContent = "A skill needs a name and its instructions.";
      return;
    }
    try {
      await this.onSave(this.editingId, body);
      this.close();
    } catch (err) {
      this.field("status").textContent = err.message;
    }
  }
}
