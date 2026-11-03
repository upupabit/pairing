"""A restarting server clears only its own unfinished replies and image jobs (owner_server), so one machine's
restart never cuts off replies another machine is still writing."""

import pytest

from app.models import ImageGenerationJob, Message
from app.schemas import ConversationCreate
from app.services import conversation_service
from app.services.image_generation_service import mark_interrupted_jobs_as_errored


async def _statuses(db, model, ids: list[str]) -> list[str]:
    db.expire_all()
    return [(await db.get(model, i)).status for i in ids]


@pytest.mark.asyncio
async def test_only_this_servers_streaming_replies_are_swept(db, user):
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    rows = [
        Message(conversation_id=conversation.id, role="assistant", content="", status="streaming", owner_server=owner)
        for owner in ("me:8000", "other:8000", None)
    ]
    db.add_all(rows)
    await db.commit()
    ids = [r.id for r in rows]

    swept = await conversation_service.mark_interrupted_messages_as_errored(db, server_id="me:8000", unowned=False)

    assert swept == 1
    assert await _statuses(db, Message, ids) == ["error", "streaming", "streaming"]


@pytest.mark.asyncio
async def test_the_primary_also_sweeps_replies_from_before_owners_existed(db, user):
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    rows = [
        Message(conversation_id=conversation.id, role="assistant", content="", status="streaming", owner_server=owner)
        for owner in ("other:8000", None)
    ]
    db.add_all(rows)
    await db.commit()

    swept = await conversation_service.mark_interrupted_messages_as_errored(db, server_id="me:8000", unowned=True)

    assert swept == 1
    assert await _statuses(db, Message, [r.id for r in rows]) == ["streaming", "error"]


@pytest.mark.asyncio
async def test_only_this_servers_image_jobs_are_swept(db, user):
    rows = [
        ImageGenerationJob(
            owner_id=user.id,
            status="running",
            prompt="p",
            checkpoint="c",
            width=64,
            height=64,
            steps=1,
            cfg=1.0,
            seed=1,
            owner_server=owner,
        )
        for owner in ("me:8000", "other:8000")
    ]
    db.add_all(rows)
    await db.commit()

    swept = await mark_interrupted_jobs_as_errored(db, server_id="me:8000", unowned=False)

    assert swept == 1
    assert await _statuses(db, ImageGenerationJob, [r.id for r in rows]) == ["error", "running"]
