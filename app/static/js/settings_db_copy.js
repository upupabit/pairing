/* Admin settings > System > Database > "Copy my data" (settings/system_server.html #db-copy-progress): starts the
 * copy job (POST /api/settings/database/copy), polls its progress and keeps the result on screen when it ends. */
class DbCopyPanel {
  static URL = "/api/settings/database/copy";
  static POLL_MS = 700;

  constructor(root) {
    this.root = root;
    this.field = (name) => root.querySelector(`[data-field="${name}"]`);
  }

  async run(form, button) {
    button.disabled = true;
    this.root.classList.remove("hidden");
    this.field("result").classList.add("hidden");
    this.show({ stage: "Starting", done: 0, total: 0 });
    try {
      let status = await api(DbCopyPanel.URL, { method: "POST", body: JSON.stringify(form) });
      // The copy goes on server-side whatever a poll does: a few failed polls (the server busy) are retried.
      let failures = 0;
      while (status.running) {
        this.show(status);
        await new Promise((resolve) => setTimeout(resolve, DbCopyPanel.POLL_MS));
        try {
          status = await api(DbCopyPanel.URL);
          failures = 0;
        } catch (err) {
          if (++failures >= 5) throw err;
        }
      }
      this.finish(status);
      if (status.ok) loadDbConfigIntoEditor({ keepStatus: true });
    } catch (err) {
      this.finish({ ok: false, message: err.message, done: 0, total: 0 });
    } finally {
      button.disabled = false;
    }
  }

  show(status) {
    const bar = this.field("bar");
    const copying = status.stage === "Copying" && status.total;
    this.field("label").textContent = copying ? `Copying ${status.table}…` : `${status.stage}…`;
    this.field("count").textContent = status.total ? `${this.number(status.done)} / ${this.number(status.total)} rows` : "";
    if (status.total) {
      bar.value = Math.round((status.done / status.total) * 100);
    } else {
      bar.removeAttribute("value"); // indeterminate until the rows are counted
    }
  }

  finish(status) {
    const bar = this.field("bar");
    bar.value = status.ok ? 100 : bar.value || 0;
    this.field("label").textContent = status.ok ? "Done" : "Stopped";
    this.field("count").textContent = status.total ? `${this.number(status.done)} / ${this.number(status.total)} rows` : "";
    const result = this.field("result");
    result.textContent = status.message || (status.ok ? "Finished." : "The copy failed.");
    result.classList.remove("hidden", "text-emerald-400", "text-red-400");
    result.classList.add(status.ok ? "text-emerald-400" : "text-red-400");
  }

  number(n) {
    return n.toLocaleString();
  }
}

const dbCopyProgressEl = document.getElementById("db-copy-progress");
const dbCopyPanel = dbCopyProgressEl ? new DbCopyPanel(dbCopyProgressEl) : null;
