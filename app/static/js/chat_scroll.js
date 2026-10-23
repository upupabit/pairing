/* Follows new text at the bottom of the chat (#messages) only while the reader is there. Scrolling up stops it, so a
long reply can stream while you read earlier messages; scrolling back to the bottom resumes it. Sending a message or
opening a chat jumps to the bottom and follows again (chat.js). */
class ChatScroll {
  static SLACK_PX = 60; // this close to the bottom still counts as "at the bottom"
  static USER_INPUT_MS = 1000; // a scroll this soon after wheel/touch/key/pointer input is the reader's own

  constructor(el) {
    this.el = el;
    this.following = true;
    this.lastInput = 0;
    const mark = () => (this.lastInput = performance.now());
    for (const type of ["wheel", "touchmove", "keydown", "pointerdown"]) el.addEventListener(type, mark, { passive: true });
    // Only the reader's own scrolling stops following. Content growing after a scroll (styles and images apply a moment
    // later) also fires "scroll" and must not count; reaching the bottom always resumes.
    el.addEventListener("scroll", () => {
      if (this.atBottom()) this.following = true;
      else if (performance.now() - this.lastInput < ChatScroll.USER_INPUT_MS) this.following = false;
    });
  }

  atBottom() {
    return this.el.scrollHeight - this.el.scrollTop - this.el.clientHeight <= ChatScroll.SLACK_PX;
  }

  /* New content arrived: keep it in view only if the reader was following. */
  follow() {
    if (this.following) this.el.scrollTop = this.el.scrollHeight;
  }

  /* Like follow, but waits for late layout (images, styles) to settle (chat.js scrollMessagesToBottom). */
  settle() {
    if (this.following) scrollMessagesToBottom();
  }

  /* The reader acted (sent a message, opened a chat): go to the bottom and follow again. */
  jump() {
    this.following = true;
    scrollMessagesToBottom();
  }
}

const chatScroll = new ChatScroll(document.getElementById("messages"));
