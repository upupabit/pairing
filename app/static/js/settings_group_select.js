/* Settings tabs with a "Configure..." selector on top (Inference engines, Knowledge): it picks which `[data-group]` block of the tab shows. The first <option> is the starting choice on a normal load. The one exception: when a Save or Start reloads the page to return to its tab (settings.js sets SETTINGS_TAB_STORAGE_KEY first), the choice is kept for that one reload, so saving the image engine doesn't jump back to the models engine. Hidden blocks stay in the DOM, so settings.js keeps binding their sections. A new option is one <option value="x"> plus one <div data-group="x">. */
class GroupSelect {
  static RETURN_TAB_KEY = "pairingSettingsActiveTab"; // settings.js SETTINGS_TAB_STORAGE_KEY
  static KEY_PREFIX = "pairingSettingsGroup:";

  constructor(select) {
    this.select = select;
    this.key = GroupSelect.KEY_PREFIX + (select.id || "group");
    this.groups = select.closest("[id^='tab-']").querySelectorAll("[data-group]");
    select.value = this.takeKeptChoice() ?? select.options[0].value;
    select.addEventListener("change", () => this.apply());
    window.addEventListener("beforeunload", () => this.keepChoiceForReturn());
    this.apply();
  }

  apply() {
    for (const group of this.groups) {
      group.classList.toggle("hidden", group.dataset.group !== this.select.value);
    }
  }

  /* The kept choice from a returning reload, once; null when none or no longer an option. */
  takeKeptChoice() {
    try {
      const kept = sessionStorage.getItem(this.key);
      sessionStorage.removeItem(this.key);
      return [...this.select.options].some((o) => o.value === kept) ? kept : null;
    } catch (_err) {
      return null; // storage blocked: start on the first option
    }
  }

  keepChoiceForReturn() {
    try {
      if (sessionStorage.getItem(GroupSelect.RETURN_TAB_KEY)) sessionStorage.setItem(this.key, this.select.value);
    } catch (_err) {
      // Storage blocked: the reload lands on the first option.
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  for (const select of document.querySelectorAll("select[data-group-select]")) new GroupSelect(select);
});
