/* The chat header's Export menu (chat.html #export-badge): Markdown from the server (routers/chat_export.py). */
class ChatExport {
  constructor() {
    this.badge = document.getElementById("export-badge");
    this.menu = document.getElementById("export-menu");
    this.conversationId = null;
    this.badge.addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = this.menu.classList.contains("hidden");
      if (opening) closeHeaderPopups("export");
      this.menu.classList.toggle("hidden", !opening);
    });
    this.menu.addEventListener("click", (event) => this.onPick(event));
    document.addEventListener("click", () => this.closeMenu());
  }

  closeMenu() {
    this.menu.classList.add("hidden");
  }

  render(conversationId) {
    this.conversationId = conversationId;
    this.badge.classList.toggle("hidden", !conversationId);
    this.menu.classList.add("hidden");
  }

  onPick(event) {
    const kind = event.target.closest("[data-export]")?.dataset.export;
    if (!kind || !this.conversationId) return;
    this.closeMenu();
    if (kind === "md") window.location.href = `/api/conversations/${this.conversationId}/export`;
  }
}

const chatExport = new ChatExport();
