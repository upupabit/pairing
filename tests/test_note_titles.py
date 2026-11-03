"""A note on the Notes page: its title is required, at most 200 characters and unique among the owner's notes (any
case); its content is required (schemas/note.py, services/note_titles.py, routers/notes.py)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models import Note
from app.routers import notes
from app.schemas.note import NoteCreate, NoteUpdate


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_an_empty_or_too_long_title_is_refused(title):
    with pytest.raises(ValidationError):
        NoteCreate(title=title, content="text")
    with pytest.raises(ValidationError):
        NoteUpdate(title=title)


def test_a_title_is_trimmed_and_an_omitted_one_stays_untitled():
    assert NoteCreate(title="  Tone  ", content="text").title == "Tone"
    assert NoteCreate(content="text").title == "Untitled note"  # the API may still create a note without one
    assert NoteUpdate(content="only the text").title is None


@pytest.mark.parametrize("content", ["", "   ", "\n\n"])
def test_empty_content_is_refused(content):
    with pytest.raises(ValidationError):
        NoteCreate(title="Tone", content=content)
    with pytest.raises(ValidationError):
        NoteCreate(title="Tone")  # content is required
    with pytest.raises(ValidationError):
        NoteUpdate(content=content)


def test_content_keeps_its_own_spacing():
    assert NoteCreate(title="List", content="- one\n  - two\n").content == "- one\n  - two\n"


@pytest.mark.asyncio
async def test_a_title_another_note_has_is_refused_in_any_case(db, user, admin_user):
    await notes.create_note(NoteCreate(title="Tone", content="text"), db=db, user=user)

    with pytest.raises(HTTPException) as again:
        await notes.create_note(NoteCreate(title="tONE", content="text"), db=db, user=user)
    assert again.value.status_code == 409 and "already have a note" in again.value.detail
    # Another user's notes don't count.
    await notes.create_note(NoteCreate(title="Tone", content="text"), db=db, user=admin_user)


@pytest.mark.asyncio
async def test_editing_keeps_its_own_title_but_cannot_take_another_s(db, user):
    first = await notes.create_note(NoteCreate(title="First", content="text"), db=db, user=user)
    second = await notes.create_note(NoteCreate(title="Second", content="text"), db=db, user=user)

    kept = await notes.update_note(first.id, NoteUpdate(title="first", content="new text"), db=db, user=user)
    assert kept.title == "first" and kept.content == "new text"
    with pytest.raises(HTTPException) as taken:
        await notes.update_note(second.id, NoteUpdate(title="FIRST"), db=db, user=user)
    assert taken.value.status_code == 409


@pytest.mark.asyncio
async def test_a_note_that_already_shared_its_title_can_still_be_saved(db, user):
    """Duplicates made before the check (or by pAIring itself) aren't blocked from saving unchanged."""
    db.add_all([Note(owner_id=user.id, title="Same"), Note(owner_id=user.id, title="Same")])
    await db.commit()
    own = (await notes.list_notes(db=db, user=user))[0]

    saved = await notes.update_note(own.id, NoteUpdate(title="Same", content="edited"), db=db, user=user)

    assert saved.content == "edited"
