/* A channel's skill set (Admin settings > Channels > Skills; PUT /api/settings/channels/{id}/skills): library
 * skills, changeable any time, used from the channel's next message on. Opened in place of the channel's row. */
class ChannelSkillsPanel {
  constructor(row, channel, onClose) {
    this.row = row;
    this.channel = channel;
    this.onClose = onClose;
    this.selected = [];
    this.library = [];
  }

  async open() {
    this.row.innerHTML = `<p class="text-xs text-slate-500">Loading skills…</p>`;
    try {
      const [chosen, library] = await Promise.all([
        api(`/api/settings/channels/${this.channel.id}/skills`),
        api("/api/admin/skills"),
      ]);
      this.selected = chosen.chosen.map((s) => s.id);
      this.started = !chosen.editable; // has messages: a change re-reads the whole history once
      this.library = library.filter((s) => s.enabled);
    } catch (err) {
      this.row.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(err.message)}</p>`;
      return;
    }
    this.draw();
  }

  draw() {
    this.row.innerHTML = `
      <div class="space-y-2">
        <p class="text-sm text-slate-200">Skills for #${escapeHtml(this.channel.name)}</p>
        <p class="text-xs text-slate-500">Used in every reply from the next message on. Members can't change them once the channel has messages; this can.</p>
        ${this.started ? `<p class="rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1.5 text-xs font-medium leading-snug text-red-400">
          This channel already has messages. Changing its skills makes the AI read the whole conversation again before
          its next reply (once). On a long channel this can take minutes, depending on your system.</p>` : ""}
        <input type="text" data-field="search" placeholder="Search skills…"
          class="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs focus:outline-none focus:border-brand-500">
        <div data-field="list" class="max-h-64 overflow-y-auto rounded-md border border-slate-700 bg-slate-950 divide-y divide-slate-800"></div>
        <p data-field="count" class="text-xs text-slate-500"></p>
        <div class="flex items-center gap-2 pt-1">
          <button type="button" data-action="save" class="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-500 transition-colors">Save</button>
          <button type="button" data-action="cancel" class="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 transition-colors">Cancel</button>
          <span data-field="status" class="text-xs text-slate-500"></span>
        </div>
      </div>`;
    this.field("search").addEventListener("input", () => this.drawList());
    this.field("list").addEventListener("change", (event) => this.onToggle(event));
    this.row.querySelector('[data-action="cancel"]').addEventListener("click", () => this.onClose());
    this.row.querySelector('[data-action="save"]').addEventListener("click", () => this.save());
    this.drawList();
  }

  field(name) {
    return this.row.querySelector(`[data-field="${name}"]`);
  }

  drawList() {
    const words = this.field("search").value.toLowerCase().split(/\s+/).filter(Boolean);
    const picked = new Set(this.selected);
    // Chosen first, so a search never hides a pick.
    const matches = this.library
      .filter((s) => picked.has(s.id) || words.every((w) => `${s.name} ${s.category}`.toLowerCase().includes(w)))
      .sort((a, b) => Number(picked.has(b.id)) - Number(picked.has(a.id)));
    this.field("list").innerHTML = matches.length
      ? matches
          .map(
            (s) => `<label class="flex cursor-pointer items-start gap-2 px-2 py-1.5 hover:bg-slate-800">
              <input type="checkbox" data-skill="${escapeHtml(s.id)}" ${picked.has(s.id) ? "checked" : ""} class="mt-0.5 accent-brand-500">
              <span class="min-w-0"><span class="text-xs text-slate-200">${escapeHtml(s.name)}</span>
              <span class="text-[11px] text-slate-500">· ${escapeHtml(s.category)}</span></span></label>`,
          )
          .join("")
      : `<p class="px-2 py-3 text-xs text-slate-500">${this.library.length ? "No skill matches." : "The library is empty: add skills on the Skills tab first."}</p>`;
    this.field("count").textContent = `${this.selected.length} selected`;
  }

  onToggle(event) {
    const id = event.target.dataset.skill;
    if (!id) return;
    this.selected = event.target.checked ? [...this.selected, id] : this.selected.filter((x) => x !== id);
    // No redraw: the rows stay put while ticking; picks go first on the next search.
    this.field("count").textContent = `${this.selected.length} selected`;
  }

  async save() {
    const status = this.field("status");
    status.textContent = "Saving…";
    try {
      await api(`/api/settings/channels/${this.channel.id}/skills`, {
        method: "PUT",
        body: JSON.stringify({ skill_ids: this.selected }),
      });
      this.onClose();
    } catch (err) {
      status.textContent = err.message;
    }
  }
}
