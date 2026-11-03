/* Notes page: checks a note's title and content before Create and Save, by the server's rules (schemas/note.py,
 * services/note_titles.py): a title is required, at most NOTE_TITLE_MAX characters, and not the title of another of
 * your notes (any case); content is required. Reads notes.js's notesCache when called. */
const NOTE_TITLE_MAX = 200;
// Red while focused too: the field's own focus colour would hide the mark.
const NOTE_TITLE_ERROR_CLASSES = ["border-red-500", "focus:border-red-500"];

/* What is wrong with `title`, or null. `note`: the note being edited (keeping its own title is always fine). */
function noteTitleProblem(title, note = null) {
  if (!title) return "Give the note a title.";
  if (title.length > NOTE_TITLE_MAX) return `Keep the title to ${NOTE_TITLE_MAX} characters or fewer.`;
  const same = (other) => other.title.toLowerCase() === title.toLowerCase();
  if (note && same(note)) return null;
  if ((notesCache || []).some((other) => other.id !== note?.id && same(other))) {
    return `You already have a note called "${title}". Pick another title.`;
  }
  return null;
}

/* Marks the field and shows the message in `statusEl`; returns true when it is fine. */
function markNoteField(field, statusEl, problem) {
  for (const name of NOTE_TITLE_ERROR_CLASSES) field.classList.toggle(name, Boolean(problem));
  field.setAttribute("aria-invalid", problem ? "true" : "false");
  statusEl.textContent = problem || "";
  statusEl.classList.toggle("text-red-400", Boolean(problem));
  if (problem) field.focus();
  return !problem;
}

function checkNoteTitle(input, statusEl, note = null) {
  return markNoteField(input, statusEl, noteTitleProblem(input.value.trim(), note));
}

function checkNoteContent(textarea, statusEl) {
  return markNoteField(textarea, statusEl, textarea.value.trim() ? null : "Write the note's content.");
}

/* Clears a field's mark as soon as it is edited; a title field also gets its length limit. */
function watchNoteField(field, statusEl) {
  if (field.tagName === "INPUT") field.maxLength = NOTE_TITLE_MAX;
  field.addEventListener("input", () => {
    if (field.getAttribute("aria-invalid") !== "true") return;
    field.classList.remove(...NOTE_TITLE_ERROR_CLASSES);
    field.setAttribute("aria-invalid", "false");
    statusEl.textContent = "";
    statusEl.classList.remove("text-red-400");
  });
}
