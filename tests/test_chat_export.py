"""A chat as Markdown (services/chat_export.py, GET /api/conversations/{id}/export)."""

import pytest
from fastapi import HTTPException

from app.models import Conversation, Message
from app.routers import chat_export as export_router
from app.services.chat_export import ChatExport


async def _chat(db, owner, title="Trip plan") -> Conversation:
    conversation = Conversation(owner_id=owner.id, title=title, model="qwen", params={})
    db.add(conversation)
    await db.commit()
    for role, content, status in [
        ("user", "Where to go?", "complete"),
        ("assistant", "Try **Lisbon**.", "complete"),
        ("user", "gone", "deleted"),
        ("system", "hidden", "complete"),
    ]:
        db.add(Message(conversation_id=conversation.id, role=role, content=content, status=status, sender_id=None))
    await db.commit()
    await db.refresh(conversation, ["messages"])
    return conversation


@pytest.mark.asyncio
async def test_markdown_has_the_title_and_visible_turns_only(db, user):
    text = ChatExport(await _chat(db, user)).markdown()

    assert text.startswith("# Trip plan\n") and "Model: qwen" in text
    assert "## You" in text and "Where to go?" in text and "## AI" in text and "Try **Lisbon**." in text
    assert "gone" not in text and "hidden" not in text


@pytest.mark.asyncio
async def test_file_name_is_safe_and_keeps_hebrew(db, user):
    assert ChatExport(await _chat(db, user, "Trip / plan?")).filename("md") == "trip-plan.md"
    assert ChatExport(await _chat(db, user, "תכנון טיול")).filename("md") == "תכנון-טיול.md"


@pytest.mark.asyncio
async def test_the_route_sends_a_download_and_hides_others_chats(db, user, admin_user):
    chat = await _chat(db, user)

    response = await export_router.export_conversation(chat.id, db=db, user=user)

    assert response.media_type.startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    with pytest.raises(HTTPException) as hidden:
        await export_router.export_conversation(chat.id, db=db, user=admin_user)
    assert hidden.value.status_code == 404
