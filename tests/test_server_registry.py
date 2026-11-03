"""services/server_registry.py: the server list, offline detection and clearing an offline server's replies."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Message, Server
from app.schemas import ConversationCreate
from app.services import conversation_service
from app.services.server_registry import ServerRegistry


def _registry(db, server_id: str) -> ServerRegistry:
    return ServerRegistry(server_id=server_id, session_factory=async_sessionmaker(db.bind, expire_on_commit=False))


@pytest.mark.asyncio
async def test_a_heartbeat_adds_the_server_then_keeps_it_fresh(db):
    registry = _registry(db, "a:8000")

    await registry.heartbeat(db)
    await registry.heartbeat(db)

    rows, now = await registry.servers(db)
    assert [r.server_id for r in rows] == ["a:8000"]
    assert registry.online(rows[0], now)


@pytest.mark.asyncio
async def test_the_leader_clears_replies_of_an_offline_server_only(db, user):
    registry = _registry(db, "a:8000")
    await registry.heartbeat(db)
    db.add(Server(server_id="gone:8000", version="1", is_primary=True, last_seen=0))
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)
    rows = [
        Message(conversation_id=conversation.id, role="assistant", content="", status="streaming", owner_server=owner)
        for owner in ("a:8000", "gone:8000")
    ]
    db.add_all(rows)
    await db.commit()
    ids = [r.id for r in rows]

    await registry.sweep_offline(db)

    db.expire_all()
    assert [(await db.get(Message, i)).status for i in ids] == ["streaming", "error"]


@pytest.mark.asyncio
async def test_only_an_offline_server_can_be_removed_from_the_list(db):
    registry = _registry(db, "a:8000")
    await registry.heartbeat(db)
    db.add(Server(server_id="gone:8000", version="1", is_primary=True, last_seen=0))
    await db.commit()

    assert await registry.forget(db, "a:8000") is False
    assert await registry.forget(db, "gone:8000") is True
    assert await db.get(Server, "gone:8000") is None
