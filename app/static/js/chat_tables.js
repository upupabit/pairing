/* Chat tables: each table in a chat bubble gets a frame that scrolls sideways when the table is wider than the bubble
(so a wide table never stretches the chat), and a Copy button. Copy puts the table on the clipboard both as HTML (so
Excel, Sheets, LibreOffice and Word paste real cells) and as tab-separated text. Styles: style.css, "Chat tables".
`frame` is called by chat.js renderMessageContent after every render, including each streamed chunk. */
class ChatTables {
  static COPIED_MS = 1500;

  static frame(container) {
    for (const table of container.querySelectorAll("table")) {
      if (table.closest(".table-box")) continue;
      const box = document.createElement("div");
      box.className = "table-box";
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "table-copy";
      button.textContent = "Copy";
      button.title = "Copy this table, to paste into Excel, Sheets or a document";
      table.replaceWith(box);
      wrap.appendChild(table);
      box.append(button, wrap);
    }
  }

  /* Tab-separated text: one line per row; tabs and line breaks inside a cell become spaces. */
  static toText(table) {
    return [...table.rows]
      .map((row) => [...row.cells].map((cell) => cell.innerText.replace(/[\t\r\n]+/g, " ").trim()).join("\t"))
      .join("\n");
  }

  static async copy(table) {
    const text = ChatTables.toText(table);
    const html = `<table>${table.innerHTML}</table>`;
    try {
      if (window.ClipboardItem && navigator.clipboard?.write) {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([text], { type: "text/plain" }),
          }),
        ]);
        return true;
      }
    } catch {
      // Falls through to the older way (also used on plain-HTTP pages, where the clipboard API is missing).
    }
    return ChatTables.copyBySelection(html, text);
  }

  /* The pre-clipboard-API way: copy from a hidden element. Works on plain-HTTP pages too. */
  static copyBySelection(html, text) {
    const holder = document.createElement("div");
    holder.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
    holder.innerHTML = html;
    document.body.appendChild(holder);
    const onCopy = (event) => {
      event.clipboardData.setData("text/html", html);
      event.clipboardData.setData("text/plain", text);
      event.preventDefault();
    };
    document.addEventListener("copy", onCopy, { once: true });
    const range = document.createRange();
    range.selectNodeContents(holder);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } finally {
      document.removeEventListener("copy", onCopy);
      selection.removeAllRanges();
      holder.remove();
    }
    return ok;
  }
}

// One listener for every table, so buttons recreated by streaming re-renders keep working.
document.addEventListener("click", async (event) => {
  const button = event.target.closest(".table-copy");
  if (!button) return;
  const table = button.closest(".table-box")?.querySelector("table");
  if (!table) return;
  const ok = await ChatTables.copy(table);
  button.textContent = ok ? "Copied" : "Copy failed";
  setTimeout(() => (button.textContent = "Copy"), ChatTables.COPIED_MS);
});
