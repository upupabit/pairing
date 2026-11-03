"""services/rolling_update.py: "Update all servers" one at a time, the leader last, stopping at an error."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Server
from app.schemas.update import PairingRestartInfo
from app.services.rolling_update import RollingUpdate, RolloutError
from app.services.server_registry import ServerRegistry


class _FakePairing:
    def __init__(self, changed: bool = True, error: str | None = None) -> None:
        self.changed, self.error, self.restarted = changed, error, False
        self.updater = self

    def in_container(self) -> bool:
        return False

    async def update_stream(self):
        yield {"step": 1, "status": "Fetching..."}
        yield {"error": self.error} if self.error else {"done": True, "changed": self.changed}

    def restart_info(self) -> PairingRestartInfo:
        return PairingRestartInfo(mode="script", can_restart=True, hint="bash scripts/restart.sh")

    def restart(self) -> None:
        self.restarted = True


async def _servers(db, *ids: str, leader: str | None = None) -> dict[str, ServerRegistry]:
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    registries = {sid: ServerRegistry(server_id=sid, session_factory=factory) for sid in ids}
    for registry in registries.values():
        await registry.heartbeat(db)
    if leader:
        await db.execute(text("DELETE FROM leader_leases"))
        await db.execute(
            text("INSERT INTO leader_leases (name, holder, expires_at) VALUES ('leader', :h, 0)"), {"h": leader}
        )
        await db.commit()
    return registries


def _rollout(registry: ServerRegistry, pairing: _FakePairing, db) -> RollingUpdate:
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    return RollingUpdate(registry=registry, pairing_factory=lambda _proxy, **_: pairing, session_factory=factory)


async def _settle(rollout: RollingUpdate) -> None:
    if rollout._task:
        await asyncio.wait_for(asyncio.shield(rollout._task), timeout=5)


@pytest.mark.asyncio
async def test_the_leader_goes_last(db):
    registries = await _servers(db, "a:1", "b:1", leader="a:1")

    rollout = await _rollout(registries["a:1"], _FakePairing(), db).start(db)

    assert rollout["queue"] == ["b:1", "a:1"]


@pytest.mark.asyncio
async def test_a_second_rollout_is_refused_while_one_runs(db):
    registries = await _servers(db, "a:1")
    rollout = _rollout(registries["a:1"], _FakePairing(), db)
    await rollout.start(db)

    with pytest.raises(RolloutError):
        await rollout.start(db)


@pytest.mark.asyncio
async def test_servers_update_one_after_another_and_report_after_restart(db):
    registries = await _servers(db, "a:1", "b:1", leader="b:1")
    pairing_a, pairing_b = _FakePairing(changed=True), _FakePairing(changed=False)
    leader = _rollout(registries["b:1"], pairing_b, db)
    a = _rollout(registries["a:1"], pairing_a, db)
    await leader.start(db)

    await leader.leader_step(db)  # a's turn
    await a.server_step(db)
    await _settle(a)
    assert pairing_a.restarted
    await _rollout(registries["a:1"], pairing_a, db).server_step(db)  # the restarted process reports
    await leader.leader_step(db)  # a done, b's turn
    await leader.server_step(db)
    await _settle(leader)
    await leader.leader_step(db)  # b up to date
    await leader.leader_step(db)  # nothing left

    result = await leader.get(db)
    assert result["status"] == "finished"
    assert result["results"] == {"a:1": "done", "b:1": "up_to_date"}
    assert result["order"] == ["a:1", "b:1"] and set(result["durations"]) == {"a:1", "b:1"}
    assert result["finished_at"] >= result["started_at"]


@pytest.mark.asyncio
async def test_an_error_stops_the_rollout(db):
    registries = await _servers(db, "a:1", "b:1", leader="b:1")
    leader = _rollout(registries["b:1"], _FakePairing(), db)
    a = _rollout(registries["a:1"], _FakePairing(error="no network"), db)
    await leader.start(db)

    await leader.leader_step(db)
    await a.server_step(db)
    await _settle(a)
    await leader.leader_step(db)

    result = await leader.get(db)
    assert result["status"] == "stopped"
    assert "no network" in result["message"]
    assert result["queue"] == ["b:1"]
    assert "a:1" in result["durations"] and result["finished_at"] is not None


@pytest.mark.asyncio
async def test_cancel_stops_before_the_next_server(db):
    registries = await _servers(db, "a:1", "b:1")
    rollout = _rollout(registries["a:1"], _FakePairing(), db)
    await rollout.start(db)

    await rollout.cancel(db)
    await rollout.leader_step(db)

    result = await rollout.get(db)
    assert result["status"] == "cancelled"
    assert result["current"] is None


@pytest.mark.asyncio
async def test_no_online_server_means_nothing_to_update(db):
    db.add(Server(server_id="gone:1", version="1", is_primary=True, last_seen=0))
    await db.commit()
    registry = ServerRegistry(server_id="x:1")

    with pytest.raises(RolloutError):
        await _rollout(registry, _FakePairing(), db).start(db)


class _SlowPairing(_FakePairing):
    """Stops halfway through downloading until `release` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def update_stream(self):
        yield {"step": 1, "total_steps": 3, "step_label": "Downloading changes", "completed": 40, "total": 100}
        await self.release.wait()
        yield {"done": True, "changed": False}


@pytest.mark.asyncio
async def test_the_updating_server_shares_its_step_and_percent_then_clears_it(db):
    registries = await _servers(db, "a:1")
    pairing = _SlowPairing()
    rollout = _rollout(registries["a:1"], pairing, db)
    await rollout.start(db)
    await rollout.leader_step(db)
    await rollout.server_step(db)

    for _ in range(50):
        await asyncio.sleep(0.01)
        if rollout.progress():
            break
    expected = {"step": 1, "total_steps": 3, "label": "Downloading changes", "percent": 40}
    assert rollout.progress() == expected
    await db.refresh(row := await db.get(Server, "a:1"))
    assert row.details["update_progress"] == expected

    pairing.release.set()
    await _settle(rollout)
    await db.refresh(row)
    assert rollout.progress() is None and "update_progress" not in (row.details or {})
