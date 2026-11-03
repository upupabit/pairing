/* Settings > Skills (settings/skills_user.html): the user's private skills via /api/skills/mine. The form is
 * SkillEditor (settings_skills_editor.js). */
class MySkills {
  static URL = "/api/skills/mine";

  constructor(root) {
    this.root = root;
    this.list = root.querySelector('[data-field="list"]');
    this.skills = [];
    this.editor = new SkillEditor(root.querySelector("[data-skill-editor]"), {
      withEnabled: false,
      onSave: (id, body) => this.save(id, body),
    });
    root.querySelector('[data-action="new"]').addEventListener("click", () => this.editor.open(null, this.categories()));
    this.list.addEventListener("click", (event) => this.onClick(event));
    document.querySelector('[data-tab="my-skills"]')?.addEventListener("click", () => this.load());
    if (!document.getElementById("tab-my-skills")?.classList.contains("hidden")) this.load();
  }

  categories() {
    return [...new Set(this.skills.map((s) => s.category))].sort();
  }

  async load() {
    this.skills = await api(MySkills.URL);
    this.list.innerHTML = this.skills.length
      ? this.skills
          .map(
            (s) => `<div class="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3">
              <p class="text-sm font-medium text-slate-200">${escapeHtml(s.name)}</p>
              <p class="text-[11px] text-slate-500">${escapeHtml(s.category)}</p>
              <p class="line-clamp-3 flex-1 text-xs text-slate-400">${escapeHtml(s.description)}</p>
              <div class="flex gap-3">
                <button type="button" data-edit="${escapeHtml(s.id)}" class="text-xs text-slate-400 hover:text-slate-200">Edit</button>
                <button type="button" data-delete="${escapeHtml(s.id)}" class="text-xs text-slate-500 hover:text-red-400">Delete</button>
              </div>
            </div>`,
          )
          .join("")
      : '<p class="col-span-full text-xs text-slate-500">No skills of your own yet.</p>';
  }

  async save(id, body) {
    await api(id ? `${MySkills.URL}/${id}` : MySkills.URL, { method: id ? "PUT" : "POST", body: JSON.stringify(body) });
    await this.load();
  }

  async onClick(event) {
    const edit = event.target.closest("[data-edit]")?.dataset.edit;
    const remove = event.target.closest("[data-delete]")?.dataset.delete;
    if (edit) this.editor.open(this.skills.find((s) => s.id === edit), this.categories());
    if (remove) {
      const skill = this.skills.find((s) => s.id === remove);
      if (!confirm(`Delete "${skill.name}"? Chats that use it stop using it.`)) return;
      await api(`${MySkills.URL}/${remove}`, { method: "DELETE" });
      await this.load();
    }
  }
}

const skillsUserEl = document.getElementById("skills-user");
if (skillsUserEl) new MySkills(skillsUserEl);
