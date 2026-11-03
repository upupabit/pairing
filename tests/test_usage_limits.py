"""Daily usage limits (services/usage_limits.py, routers/usage_limits_admin.py, the check in routers/chat.py)."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.models import Conversation, Message
from app.models._base import utcnow
from app.routers import usage_limits_admin
from app.schemas.usage_limits import UsageLimits, UserUsageLimits
from app.services.usage_limits import UsageLimitService


async def _reply(db, user, tokens=None, age=timedelta()):
    chat = Conversation(owner_id=user.id, params={})
    db.add(chat)
    await db.commit()
    asked = Message(conversation_id=chat.id, role="user", content="q", sender_id=user.id)
    db.add(asked)
    await db.commit()
    stats = {"first_token_ms": 1, "total_ms": 2, "output_tokens": tokens} if tokens else None
    db.add(
        Message(
            conversation_id=chat.id,
            role="assistant",
            content="a",
            reply_to_message_id=asked.id,
            stats=stats,
            created_at=utcnow() - age,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_counts_the_last_24_hours_only(db, user):
    await _reply(db, user, tokens=100)
    await _reply(db, user)  # an engine that sends no counts
    await _reply(db, user, tokens=999, age=timedelta(hours=30))

    assert await UsageLimitService(db).used(user.id) == (2, 100)


@pytest.mark.asyncio
async def test_default_and_user_limits_block_a_new_reply(db, user):
    service = UsageLimitService(db)
    await _reply(db, user, tokens=50)
    await service.check(user)  # no limits yet

    await service.set_defaults(UsageLimits(replies_per_day=1))
    with pytest.raises(HTTPException) as over:
        await service.check(user)
    assert over.value.status_code == 429 and "1 AI replies" in over.value.detail

    await service.set_for_user(user, UserUsageLimits(replies_per_day=0, tokens_per_day=40))  # 0: no reply limit
    with pytest.raises(HTTPException) as tokens:
        await service.check(user)
    assert "40 generated tokens" in tokens.value.detail

    usage = await service.set_for_user(user, UserUsageLimits())  # back to the default
    assert usage.effective.replies_per_day == 1 and usage.override.replies_per_day is None


@pytest.mark.asyncio
async def test_admins_are_never_limited(db, admin_user):
    await UsageLimitService(db).set_defaults(UsageLimits(replies_per_day=1))
    await _reply(db, admin_user)
    await _reply(db, admin_user)

    await UsageLimitService(db).check(admin_user)
    assert (await usage_limits_admin.get_user_limits(admin_user.id, db=db, _admin=admin_user)).exempt


@pytest.mark.asyncio
async def test_the_admin_routes(db, user, admin_user):
    saved = await usage_limits_admin.set_defaults(UsageLimits(tokens_per_day=500), db=db, _admin=admin_user)
    assert saved.tokens_per_day == 500
    assert (await usage_limits_admin.get_defaults(db=db, _admin=admin_user)).tokens_per_day == 500
    out = await usage_limits_admin.set_user_limits(
        user.id, UserUsageLimits(tokens_per_day=10), db=db, _admin=admin_user
    )
    assert out.effective.tokens_per_day == 10
    with pytest.raises(HTTPException) as missing:
        await usage_limits_admin.get_user_limits("nobody", db=db, _admin=admin_user)
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_the_chat_route_refuses_before_streaming(db, user):
    from app.routers import chat as chat_router

    await UsageLimitService(db).set_defaults(UsageLimits(replies_per_day=1))
    await _reply(db, user)
    chat = Conversation(owner_id=user.id, params={}, model="m")
    db.add(chat)
    await db.commit()

    with pytest.raises(HTTPException) as over:
        await chat_router.stream_reply(chat.id, content="hi", ask_ai=True, attachments=[], db=db, user=user)
    assert over.value.status_code == 429
