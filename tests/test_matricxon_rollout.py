"""services/matricxon_rollout.py and matricxon_node_update.py: "Update all nodes" against fake Matricxon nodes
(httpx.MockTransport) that update, restart on a new commit and rejoin."""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.schemas import MatricxonServerConfig
from app.services import matricxon_rollout as rollout_module
from app.services.matricxon_node_update import NodeUpdate
from app.services.matricxon_rollout import MatricxonRollout
from app.services.rolling_update import RolloutError


class _Node:
    """One fake node: POST /api/update starts it, two status polls later it restarts on a new commit."""

    def __init__(self, node_id: str, update: int = 202, changed: bool = True, fail: str | None = None) -> None:
        self.node_id, self.update, self.changed, self.fail = node_id, update, changed, fail
        self.commit, self.polls, self.down = "aaa1111", 0, 0
        self.started = False
        self.updating_polls = 1  # how many status polls say "updating" before it restarts

    def handle(self, request: httpx.Request, leader: str) -> httpx.Response:
        path = request.url.path
        if self.down:
            self.down -= 1
            raise httpx.ConnectError("restarting")
        if path == "/api/version":
            return httpx.Response(200, json={"version": "2.0", "commit": self.commit})
        if path == "/api/consensus/status":
            return httpx.Response(
                200, json={"enabled": True, "has_quorum": True, "node_id": self.node_id, "leader": leader}
            )
        if path == "/api/update" and request.method == "POST":
            self.started = True
            return httpx.Response(
                self.update, json={"detail": "This node runs in a container: update its image instead."}
            )
        if path == "/api/update":
            self.polls += 1
            if self.fail:
                return httpx.Response(200, json={"state": "error", "error": self.fail})
            if not self.changed:
                return httpx.Response(200, json={"state": "up_to_date"})
            if self.polls <= self.updating_polls:
                return httpx.Response(
                    200, json={"state": "updating", "step": 1, "total_steps": 3, "label": "x", "percent": 50}
                )
            self.commit, self.down = "bbb2222", 1
            return httpx.Response(200, json={"state": "restarting"})
        return httpx.Response(404)


@pytest.fixture
def cluster(db, monkeypatch):
    """Two nodes, b is the consensus leader; returns (rollout, nodes)."""
    monkeypatch.setattr(NodeUpdate, "POLL_SECONDS", 0)
    nodes = {"http://a:8420": _Node("A"), "http://b:8420": _Node("B")}

    def handler(request: httpx.Request) -> httpx.Response:
        return nodes[f"http://{request.url.host}:{request.url.port}"].handle(request, leader="B")

    config = MatricxonServerConfig(mode="remote", remote_hosts=list(nodes), cluster_role="seed")

    async def get_config(_db):
        return config

    monkeypatch.setattr(rollout_module.settings_service, "get_matricxon_server_config", get_config)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    return MatricxonRollout(session_factory=factory, transport=httpx.MockTransport(handler)), nodes


async def _finish(rollout: MatricxonRollout) -> None:
    await asyncio.wait_for(rollout._task, timeout=10)


@pytest.mark.asyncio
async def test_every_node_updates_the_leader_last_and_rejoins(db, cluster):
    rollout, nodes = cluster

    started = await rollout.start(db)
    assert started["order"] == ["http://a:8420", "http://b:8420"] and started["leader"] == "http://b:8420"
    await _finish(rollout)

    result = await rollout.get(db)
    assert result["status"] == "finished"
    assert result["results"] == {"http://a:8420": "done", "http://b:8420": "done"}
    assert set(result["durations"]) == set(nodes) and result["finished_at"] is not None


@pytest.mark.asyncio
async def test_an_error_stops_before_the_next_node(db, cluster):
    rollout, nodes = cluster
    nodes["http://a:8420"].fail = "git fetch failed: no network"

    await rollout.start(db)
    await _finish(rollout)

    result = await rollout.get(db)
    assert result["status"] == "stopped" and "no network" in result["message"]
    assert not nodes["http://b:8420"].started


@pytest.mark.asyncio
async def test_a_node_in_a_container_is_skipped_and_one_up_to_date_is_not_restarted(db, cluster):
    rollout, nodes = cluster
    nodes["http://a:8420"].update = 409
    nodes["http://b:8420"].changed = False

    await rollout.start(db)
    await _finish(rollout)

    result = await rollout.get(db)
    assert result["status"] == "finished"
    assert result["results"]["http://a:8420"].startswith("skipped: This node runs in a container")
    assert result["results"]["http://b:8420"] == "up_to_date"


@pytest.mark.asyncio
async def test_an_older_matricxon_without_the_update_call_stops_with_how_to_fix(db, cluster):
    rollout, nodes = cluster
    nodes["http://a:8420"].update = 404

    await rollout.start(db)
    await _finish(rollout)

    message = (await rollout.get(db))["message"]
    assert "older Matricxon (2.0)" in message and "git pull, then restart it" in message


@pytest.mark.asyncio
async def test_cancel_stops_before_the_next_node_and_a_second_start_is_refused(db, cluster, monkeypatch):
    rollout, nodes = cluster
    monkeypatch.setattr(NodeUpdate, "POLL_SECONDS", 0.02)
    nodes["http://a:8420"].updating_polls = 10
    await rollout.start(db)
    with pytest.raises(RolloutError):
        await rollout.start(db)

    await rollout.cancel(db)
    await _finish(rollout)

    result = await rollout.get(db)
    assert result["status"] == "cancelled" and not nodes["http://b:8420"].started
    assert result["results"] == {"http://a:8420": "done"}  # the node already updating finished


@pytest.mark.asyncio
async def test_a_rollout_whose_server_stopped_reads_as_stopped(db, cluster):
    rollout, _nodes = cluster
    await rollout.start(db)
    await _finish(rollout)
    stored = await rollout.get(db)
    stored.update(status="running", touched_at=0)
    await rollout._write(db, stored)

    result = await rollout.get(db)
    assert result["status"] == "stopped" and "stopped" in result["message"]


@pytest.mark.asyncio
async def test_the_overview_shows_the_current_node_stage_and_the_versions(db, cluster):
    rollout, _nodes = cluster
    await rollout.start(db)
    await _finish(rollout)
    stored = await rollout.get(db)
    stored.update(current="http://a:8420", node_state={"state": "updating", "progress": {"step": 2}})
    await rollout._write(db, stored)

    overview = await rollout.overview(db)
    by_id = {n.server_id: n for n in overview.servers}
    assert by_id["http://a:8420"].update_progress == {"step": 2} and by_id["http://b:8420"].leader

    versions = {v.host: v for v in await rollout.node_versions(db)}
    assert versions["http://a:8420"].commit == "bbb2222" and versions["http://b:8420"].leader


@pytest.mark.asyncio
async def test_the_routes_report_nothing_running_and_refuse_a_second_start(db, cluster, monkeypatch):
    from fastapi import HTTPException

    from app.routers import matricxon_update_admin as routes

    rollout, _nodes = cluster
    monkeypatch.setattr(routes, "matricxon_rollout", rollout)
    assert (await routes.get_update_all(db=db, _admin=None)).rollout is None

    assert (await routes.start_update_all(db=db, _admin=None)).rollout.status == "running"
    with pytest.raises(HTTPException) as exc:
        await routes.start_update_all(db=db, _admin=None)
    assert exc.value.status_code == 409
    await _finish(rollout)
