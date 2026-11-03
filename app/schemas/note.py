"""Request/response shapes for app/routers/notes.py."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import PinType


class NotePinCreate(BaseModel):
    """One entry of NoteCreate/NoteUpdate `pins`: a conversation and a role. The list replaces the note's
    entire pin set (routers/notes.py _sync_pins), so the Notes page saves text and pins in one request.
    """

    conversation_id: str
    pin_type: PinType


NOTE_TITLE_MAX = 200


def _clean_title(title: str | None) -> str | None:
    """Trimmed; a title that is empty or only spaces is refused (the Notes page checks the same, notes_titles.js)."""
    if title is None:
        return None
    title = title.strip()
    if not title:
        raise ValueError("A note needs a title.")
    return title


def _require_content(content: str | None) -> str | None:
    """Content that is empty or only spaces is refused (the Notes page checks the same, notes_titles.js). Kept as
    written otherwise: its line breaks and indents are the note."""
    if content is not None and not content.strip():
        raise ValueError("A note needs some content.")
    return content


class NoteCreate(BaseModel):
    title: str = Field("Untitled note", max_length=NOTE_TITLE_MAX)
    content: str
    pins: list[NotePinCreate] = []

    _title = field_validator("title")(_clean_title)
    _content = field_validator("content")(_require_content)


class NoteUpdate(BaseModel):
    """title/content optional so a save can touch one. `pins`, when present, replaces the whole pin set
    (omit to leave untouched; the Notes page always sends it).
    """

    title: str | None = Field(None, max_length=NOTE_TITLE_MAX)
    content: str | None = None
    pins: list[NotePinCreate] | None = None

    _title = field_validator("title")(_clean_title)
    _content = field_validator("content")(_require_content)


class NotePinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    # Denormalized at read time (routers/notes.py) so the Notes page shows "pinned to <chat title>" without a request
    # per pin.
    conversation_title: str
    pin_type: PinType


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    pins: list[NotePinOut] = []
    # True for the 2 notes note_service.seed_default_notes creates (persona/rules); the Notes page
    # disables Delete for them (guard in DELETE /api/notes/{note_id}).
    is_default: bool = False


class NoteSlotUpdate(BaseModel):
    """Body for PUT /api/notes/slots/{conversation_id}/{pin_type}.

    only_this_chat=False (default) updates the user's shared default note (all chats); True forks a private
    override pinned to this conversation.
    """

    content: str = ""
    only_this_chat: bool = False


class DefaultNotesEnabledConfig(BaseModel):
    """GET/PUT /api/notes/default-notes-enabled body
    (default_notes_setting.get_default_notes_enabled/set_default_notes_enabled).
    Off by default: a new chat/channel starts with all 3 default notes off (icons faded, see NoteSlotOut.active)
    until the user enables this (Settings > Account) or one slot for one chat.
    """

    enabled: bool = False


class NoteSlotOut(BaseModel):
    """One of a conversation's 2 persona/rules slots for the chat page icons (GET/PUT/DELETE
    /api/notes/slots/{conversation_id}/...). Simpler than NoteOut.pins: one primary note per slot, vs. the
    many-per-type pinning used for prompt building (note_service.resolve_conversation_notes).
    """

    pin_type: PinType
    active: bool  # False = off for this chat: icon faded, not hidden
    is_override: bool  # True = private per-chat fork, not the shared default
    # Set whenever the user has a note for this slot, even when active=False, so a faded icon's editor has content to
    # show.
    note_id: str | None = None
    title: str | None = None
    content: str | None = None
