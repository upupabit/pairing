/* Closes the header badge popups (chat.js closeHeaderPopups) on a press anywhere outside them.
 * Pointerdown, not click: a text selection dragged out of the note editor doesn't close it. */
class HeaderPopupDismiss {
  static POPUPS = ["slot-editor", "model-picker", "skills-picker", "export-menu", "thinking-confirm"];
  // The badges toggle their own popups.
  static OPENERS = ["pinned-badges", "skills-badge", "model-badge", "thinking-chip", "export-badge"];

  constructor() {
    document.addEventListener("pointerdown", (event) => this.onPress(event));
  }

  onPress(event) {
    // composedPath: still right when a handler re-drew the pressed element.
    const ids = new Set(event.composedPath().map((el) => el.id).filter(Boolean));
    const inside = [...HeaderPopupDismiss.POPUPS, ...HeaderPopupDismiss.OPENERS].some((id) => ids.has(id));
    if (!inside) closeHeaderPopups();
  }
}

const headerPopupDismiss = new HeaderPopupDismiss();
