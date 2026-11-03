"""routers/servers_admin.py and services/servers_overview.py (router functions called directly). The test
database is SQLite; `shared` makes it behave like MySQL."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Server
from app.routers import servers_admin
from app.services import servers_overview as overview_module
from app.services.server_heartbeat import ServerHeartbeat
from app.services.server_registry import server_registry


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(overview_module, "shared_database", lambda _db: True)


@pytest.mark.asyncio
async def test_the_list_marks_this_server_and_offline_ones(db, shared):
    await server_registry.heartbeat(db)
    db.add(Server(server_id="gone:8000", version="1", is_primary=True, last_seen=0))
    await db.commit()

    overview = await servers_admin.list_servers(db=db, _admin=None)

    by_id = {s.server_id: s for s in overview.servers}
    assert by_id[server_registry.server_id].this_server and by_id[server_registry.server_id].online
    assert not by_id["gone:8000"].online
    assert overview.rollout is None and overview.shared_database


@pytest.mark.asyncio
async def test_update_all_starts_once_and_refuses_a_second_start(db, shared):
    await server_registry.heartbeat(db)

    overview = await servers_admin.update_all(db=db, _admin=None)
    assert overview.rollout.status == "running"

    with pytest.raises(HTTPException) as exc:
        await servers_admin.update_all(db=db, _admin=None)
    assert exc.value.status_code == 409

    cancelled = await servers_admin.cancel_update_all(db=db, _admin=None)
    assert cancelled.rollout.status == "cancelled"


@pytest.mark.asyncio
async def test_an_online_server_cannot_be_removed(db, shared):
    await server_registry.heartbeat(db)

    with pytest.raises(HTTPException) as exc:
        await servers_admin.forget_server(server_registry.server_id, db=db, _admin=None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_on_sqlite_the_list_is_this_machine_and_update_all_is_refused(db, monkeypatch):
    monkeypatch.setattr(overview_module.instance_process, "read_tracking", lambda: {1: {"pid": 1}})
    monkeypatch.setattr(overview_module.instance_process, "is_alive", lambda _pid: True)

    overview = await servers_admin.list_servers(db=db, _admin=None)

    assert overview.shared_database is False
    assert [(s.this_server, s.is_primary, s.leader) for s in overview.servers] == [
        (True, True, True),
        (False, False, False),
    ]
    assert len({s.machine for s in overview.servers}) == 1  # the instance groups under its server
    with pytest.raises(HTTPException) as exc:
        await servers_admin.update_all(db=db, _admin=None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_on_sqlite_the_heartbeat_writes_nothing(db):
    heartbeat = ServerHeartbeat(session_factory=async_sessionmaker(db.bind, expire_on_commit=False))

    await heartbeat.tick()

    assert await db.get(Server, server_registry.server_id) is None


@pytest.mark.asyncio
async def test_the_updating_server_shows_its_progress_and_the_rollout_its_order(db, shared):
    await server_registry.heartbeat(db, {"update_progress": {"step": 2, "total_steps": 3, "label": "x", "percent": 5}})
    overview = await servers_admin.update_all(db=db, _admin=None)
    assert overview.rollout.order == [server_registry.server_id] and overview.server_time >= overview.rollout.started_at
    assert overview.servers[0].update_progress is None  # only while it is "updating"

    await server_registry.set_update_state(db, overview.rollout.id, "updating")
    overview = await servers_admin.list_servers(db=db, _admin=None)

    assert overview.servers[0].update_progress["step"] == 2



@pytest.mark.asyncio
async def test_a_server_and_its_instance_on_one_machine_share_the_machine_name(db, shared):
    await server_registry.heartbeat(db, {"machine": "web1"})
    db.add(Server(server_id="web1:8001", version="1", is_primary=False, last_seen=0, details={"machine": "web1"}))
    db.add(Server(server_id="old:8000", version="1", is_primary=True, last_seen=0))  # an older server: no "machine"
    await db.commit()

    by_id = {s.server_id: s for s in (await servers_admin.list_servers(db=db, _admin=None)).servers}

    assert by_id[server_registry.server_id].machine == by_id["web1:8001"].machine == "web1"
    assert by_id["old:8000"].machine == "old"  # from its name
