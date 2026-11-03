/* Admin settings > Skills (settings/skills_admin.html): the shared library (/api/admin/skills) and the template
 * gallery (/api/admin/skills/templates), via services/skill_library.py. The form is SkillEditor. */
class SkillsAdmin {
  static URL = "/api/admin/skills";

  constructor(root) {
    this.root = root;
    this.field = (name) => root.querySelector(`[data-field="${name}"]`);
    this.skills = [];
    this.templates = [];
    this.editor = new SkillEditor(root.querySelector("[data-skill-editor]"), {
      withEnabled: true,
      onSave: (id, body) => this.saveSkill(id, body),
    });
    root.querySelector('[data-action="new"]').addEventListener("click", () => this.editor.open(null, this.categories()));
    this.field("search").addEventListener("input", () => this.renderSkills());
    this.field("filter-category").addEventListener("change", () => this.renderSkills());
    this.field("list").addEventListener("click", (event) => this.onSkillClick(event));
    this.field("list").addEventListener("change", (event) => this.onToggle(event));
    let timer;
    this.field("gallery-search").addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => this.loadGallery(), 250);
    });
    this.field("gallery-category").addEventListener("change", () => this.loadGallery());
    this.field("gallery").addEventListener("click", (event) => this.onGalleryClick(event));
    root.querySelector('[data-action="add-category"]').addEventListener("click", () => this.addCategory());
    this.loaded = false;
    document.querySelector('[data-tab="skills"]')?.addEventListener("click", () => this.load());
    if (!document.getElementById("tab-skills")?.classList.contains("hidden")) this.load();
  }

  async load() {
    await Promise.all([this.loadSkills(), this.loaded ? null : this.loadGallery()]);
    this.loaded = true;
  }

  categories() {
    return [...new Set(this.skills.map((s) => s.category))].sort();
  }

  async loadSkills() {
    this.skills = await api(SkillsAdmin.URL);
    const select = this.field("filter-category");
    const current = select.value;
    select.innerHTML = `<option value="">All categories</option>${this.categories().map((c) => `<option>${escapeHtml(c)}</option>`).join("")}`;
    select.value = this.categories().includes(current) ? current : "";
    this.renderSkills();
  }

  renderSkills() {
    const words = this.field("search").value.toLowerCase().split(/\s+/).filter(Boolean);
    const category = this.field("filter-category").value;
    const shown = this.skills.filter(
      (s) => (!category || s.category === category) && words.every((w) => `${s.name} ${s.description}`.toLowerCase().includes(w)),
    );
    const enabled = this.skills.filter((s) => s.enabled).length;
    this.field("summary").textContent = this.skills.length
      ? `${this.skills.length} skill${this.skills.length === 1 ? "" : "s"}, ${enabled} enabled.`
      : "No skills yet: add some from the gallery below, or write your own.";
    this.field("list").innerHTML = shown.map((s) => this.skillRow(s)).join("");
  }

  skillRow(s) {
    const source = s.source ? '<span class="rounded-full border border-slate-700 px-1.5 text-[10px] text-slate-400">Fabric</span>' : "";
    return `<div class="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 ${s.enabled ? "" : "opacity-60"}">
      <div class="flex items-start gap-2">
        <label class="mt-0.5 shrink-0" title="Enabled: users can choose it"><input type="checkbox" data-toggle="${escapeHtml(s.id)}" ${s.enabled ? "checked" : ""} class="accent-brand-500"></label>
        <p class="min-w-0 flex-1 text-sm font-medium text-slate-200">${escapeHtml(s.name)}</p>
      </div>
      <p class="text-[11px] text-slate-500">${escapeHtml(s.category)} ${source}</p>
      <p class="line-clamp-3 flex-1 text-xs text-slate-400">${escapeHtml(s.description)}</p>
      <div class="flex gap-3">
        <button type="button" data-edit="${escapeHtml(s.id)}" class="text-xs text-slate-400 hover:text-slate-200">Edit</button>
        <button type="button" data-delete="${escapeHtml(s.id)}" class="text-xs text-slate-500 hover:text-red-400">Delete</button>
      </div>
    </div>`;
  }

  async saveSkill(id, body) {
    await api(id ? `${SkillsAdmin.URL}/${id}` : SkillsAdmin.URL, { method: id ? "PUT" : "POST", body: JSON.stringify(body) });
    await this.loadSkills();
  }

  async onSkillClick(event) {
    const edit = event.target.closest("[data-edit]")?.dataset.edit;
    const remove = event.target.closest("[data-delete]")?.dataset.delete;
    if (edit) this.editor.open(this.skills.find((s) => s.id === edit), this.categories());
    if (remove) {
      const skill = this.skills.find((s) => s.id === remove);
      if (!confirm(`Delete "${skill.name}"? Chats that use it stop using it.`)) return;
      await api(`${SkillsAdmin.URL}/${remove}`, { method: "DELETE" });
      await this.loadSkills();
      this.loadGallery();
    }
  }

  async onToggle(event) {
    const id = event.target.dataset.toggle;
    if (!id) return;
    const skill = this.skills.find((s) => s.id === id);
    await this.saveSkill(id, { ...skill, enabled: event.target.checked });
  }

  async loadGallery() {
    const q = this.field("gallery-search").value.trim();
    const category = this.field("gallery-category").value;
    const params = new URLSearchParams({ q, ...(category ? { category } : {}) });
    const page = await api(`${SkillsAdmin.URL}/templates?${params}`);
    this.templates = page.items;
    const select = this.field("gallery-category");
    if (!select.options.length) {
      select.innerHTML = `<option value="">All categories</option>${Object.entries(page.categories)
        .map(([name, count]) => `<option value="${escapeHtml(name)}">${escapeHtml(name)} (${count})</option>`)
        .join("")}`;
    }
    const credit = page.sources
      .map((s) => `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener" class="underline underline-offset-2">${escapeHtml(s.source_name)}</a> (${escapeHtml(s.license)} License)`)
      .join(", ");
    this.field("credit").innerHTML = `Ready-made skills from ${credit}. Adding one copies it into your skills, where you can edit it.`;
    const notAdded = page.items.filter((t) => !t.added).length;
    const addAll = this.root.querySelector('[data-action="add-category"]');
    addAll.classList.toggle("hidden", !category || !notAdded);
    addAll.textContent = `Add all ${notAdded} in ${category}`;
    this.field("gallery-status").textContent = `${page.total} template${page.total === 1 ? "" : "s"}${q || category ? " found" : ""}.`;
    this.field("gallery").innerHTML = page.items.map((t) => this.templateRow(t)).join("");
  }

  templateRow(t) {
    const action = t.added
      ? '<span class="shrink-0 text-xs text-emerald-400">Added</span>'
      : `<button type="button" data-add="${escapeHtml(t.key)}" class="shrink-0 rounded-md border border-slate-700 px-2 py-0.5 text-xs text-slate-200 hover:bg-slate-800">Add</button>`;
    return `<div class="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 h-full">
      <p class="text-sm font-medium text-slate-200">${escapeHtml(t.name)}</p>
      <p class="text-[11px] text-slate-500">${t.categories.map(escapeHtml).join(", ")}</p>
      <p class="line-clamp-3 flex-1 text-xs text-slate-400">${escapeHtml(t.description)}</p>
      <div class="flex items-center justify-between gap-2">
        <button type="button" data-preview="${escapeHtml(t.key)}" class="text-xs text-slate-400 hover:text-slate-200">Preview</button>
        ${action}
      </div>
      <pre data-preview-of="${escapeHtml(t.key)}" class="hidden max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-2 text-[11px] text-slate-400">${escapeHtml(t.content)}</pre>
    </div>`;
  }

  async onGalleryClick(event) {
    const preview = event.target.closest("[data-preview]")?.dataset.preview;
    if (preview) {
      // An open preview spans the whole row, so the instructions stay readable.
      const text = this.field("gallery").querySelector(`[data-preview-of="${CSS.escape(preview)}"]`);
      const open = text.classList.toggle("hidden") === false;
      text.closest("div").classList.toggle("col-span-full", open);
    }
    const add = event.target.closest("[data-add]")?.dataset.add;
    if (add) await this.addTemplates({ keys: [add] });
  }

  async addCategory() {
    const category = this.field("gallery-category").value;
    if (category && confirm(`Add every template in ${category} to your skills?`)) await this.addTemplates({ category });
  }

  async addTemplates(body) {
    try {
      const result = await api(`${SkillsAdmin.URL}/templates/add`, { method: "POST", body: JSON.stringify(body) });
      await Promise.all([this.loadSkills(), this.loadGallery()]);
      this.field("gallery-status").textContent = `Added ${result.added}${result.already ? `, ${result.already} already there` : ""}.`;
    } catch (err) {
      this.field("gallery-status").textContent = err.message;
    }
  }
}

const skillsAdminEl = document.getElementById("skills-admin");
if (skillsAdminEl) new SkillsAdmin(skillsAdminEl);
