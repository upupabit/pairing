"""A note's title is unique among its owner's notes, ignoring case (the Notes page and its pin pickers tell notes apart
by title). Checked when a title is set or changed from the Notes page; notes made for a chat or channel
(note_slot_service.py, note_service.freeze_channel_notes) are named by pAIring and not checked."""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note


async def ensure_unique_title(db: AsyncSession, owner_id: str, title: str, note: Note | None = None) -> None:
    """409 when another of `owner_id`'s notes has this title. Keeping a note's own title is always fine, so a note
    that shared its title before this check can still be saved."""
    if note is not None and note.title.casefold() == title.casefold():
        return
    query = select(Note.id).where(Note.owner_id == owner_id, func.lower(Note.title) == title.lower())
    if note is not None:
        query = query.where(Note.id != note.id)
    if (await db.execute(query.limit(1))).first():
        raise HTTPException(status_code=409, detail=f'You already have a note called "{title}". Pick another title.')
