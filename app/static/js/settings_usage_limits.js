/* Daily usage limits (Admin settings > Users; /api/admin/usage-limits, services/usage_limits.py):
 * the default box above the list, and one user's override and use, opened in place of its row. */
class UsageLimitsDefaults {
  constructor(box) {
    this.box = box;
    this.field = (name) => box.querySelector(`[data-field="${name}"]`);
    box.querySelector('[data-action="save"]').addEventListener("click", () => this.save());
  }

  async load() {
    try {
      const limits = await api("/api/admin/usage-limits");
      this.field("replies_per_day").value = limits.replies_per_day;
      this.field("tokens_per_day").value = limits.tokens_per_day;
    } catch (err) {
      this.field("status").textContent = err.message;
    }
  }

  async save() {
    const body = {
      replies_per_day: Number(this.field("replies_per_day").value) || 0,
      tokens_per_day: Number(this.field("tokens_per_day").value) || 0,
    };
    this.field("status").textContent = "Saving…";
    try {
      await api("/api/admin/usage-limits", { method: "PUT", body: JSON.stringify(body) });
      this.field("status").textContent = "Saved.";
    } catch (err) {
      this.field("status").textContent = err.message;
    }
  }
}

class UserLimitsPanel {
  constructor(row, user, onClose) {
    this.row = row;
    this.user = user;
    this.onClose = onClose;
    this.url = `/api/admin/usage-limits/users/${encodeURIComponent(user.id)}`;
  }

  async open() {
    this.row.innerHTML = `<p class="text-xs text-slate-500">Loading…</p>`;
    try {
      this.draw(await api(this.url));
    } catch (err) {
      this.row.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(err.message)}</p>`;
    }
  }

  draw(usage) {
    const input = (name, value, placeholder) =>
      `<input data-field="${name}" type="number" min="0" value="${value ?? ""}" placeholder="${escapeHtml(placeholder)}"
        class="mt-1 block w-40 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-500">`;
    const limit = (n) => (n ? n.toLocaleString() : "no limit");
    this.row.innerHTML = `
      <div class="space-y-2">
        <p class="text-sm text-slate-200">Daily limits for ${escapeHtml(this.user.username)}</p>
        <p class="text-xs text-slate-500">Last 24 hours: ${usage.replies_used} replies, ${usage.tokens_used.toLocaleString()} tokens.
          Limits now: replies ${limit(usage.effective.replies_per_day)}, tokens ${limit(usage.effective.tokens_per_day)}.
          Leave a field empty to use the default; 0 means no limit.</p>
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-xs text-slate-400">AI replies${input("replies_per_day", usage.override.replies_per_day, "Default")}</label>
          <label class="text-xs text-slate-400">Generated tokens${input("tokens_per_day", usage.override.tokens_per_day, "Default")}</label>
          <button data-action="save" type="button" class="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-500 transition-colors">Save</button>
          <button data-action="cancel" type="button" class="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 transition-colors">Close</button>
          <span data-field="status" class="text-xs text-slate-500"></span>
        </div>
      </div>`;
    this.row.querySelector('[data-action="cancel"]').addEventListener("click", () => this.onClose());
    this.row.querySelector('[data-action="save"]').addEventListener("click", () => this.save());
  }

  async save() {
    const value = (name) => {
      const text = this.row.querySelector(`[data-field="${name}"]`).value.trim();
      return text === "" ? null : Number(text);
    };
    const status = this.row.querySelector('[data-field="status"]');
    status.textContent = "Saving…";
    try {
      const body = { replies_per_day: value("replies_per_day"), tokens_per_day: value("tokens_per_day") };
      this.draw(await api(this.url, { method: "PUT", body: JSON.stringify(body) }));
      this.row.querySelector('[data-field="status"]').textContent = "Saved.";
    } catch (err) {
      status.textContent = err.message;
    }
  }
}

const usageLimitsBox = document.getElementById("usage-limits-defaults");
if (usageLimitsBox) new UsageLimitsDefaults(usageLimitsBox).load();
