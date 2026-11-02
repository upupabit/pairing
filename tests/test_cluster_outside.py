"""Cluster page > Non-cluster hosts: listing pAIring's hosts outside the cluster and removing them in one save."""

import httpx
import pytest
from fastapi import HTTPException

from app.routers import cluster_outside
from app.schemas import MatricxonServerConfig
from app.schemas.cluster_outside import OutsideRemove
from app.services import matricxon_pool, server_pool_broadcast, settings_service
from app.services.cluster_errors import NodeNotAllowedError
from app.services.cluster_outside import OutsideHosts

SEED, GONE, OLD = "http://a:1", "http://b:2", "http://c:3"


@pytest.fixture(autouse=True)
def _quiet_broadcast(monkeypatch):
    async def none(_path):
        return []

    monkeypatch.setattr(server_pool_broadcast, "broadcast_refresh", none)
    yield
    matricxon_pool.refresh_from_config(MatricxonServerConfig())


class FakeNodes:
    """`up` hosts answer; the first one is the seed, listing `members` as the cluster's nodes."""

    def __init__(self, up: list[str], members: dict[str, str] | None = None) -> None:
        self.up = {httpx.URL(h).host for h in up}
        self.seed = httpx.URL(up[0]).host if up else None
        self.members = members
        self.resets: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host not in self.up:
            raise httpx.ConnectError("down")
        if request.url.path == "/api/consensus/status":
            if self.members is None or host != self.seed:
                return httpx.Response(200, json={"enabled": False})
            status = {"enabled": True, "node_id": "id-a", "is_voter": True, "role": "leader", "has_quorum": True}
            return httpx.Response(200, json=status | {"nodes": self.members})
        if request.url.path == "/api/cluster/reset":
            self.resets.append(host)
        return httpx.Response(200, json={})


async def _save(db, **fields) -> MatricxonServerConfig:
    config = MatricxonServerConfig(**fields)
    await settings_service.set_matricxon_server_config(db, config)
    matricxon_pool.refresh_from_config(config)
    return config


def _cluster(**extra) -> dict:
    return {"mode": "remote", "remote_hosts": [SEED, GONE], "cluster_role": "seed", **extra}


@pytest.mark.asyncio
async def test_with_cluster_mode_off_it_is_the_remote_host_list(db):
    await _save(db, mode="remote", remote_hosts=[SEED, GONE])
    state = await OutsideHosts(db, httpx.MockTransport(FakeNodes([SEED]))).read()
    assert (state.cluster, state.known) == (False, True)
    assert [(h.host, h.places, h.reachable) for h in state.hosts] == [
        (SEED, ["remote"], True),
        (GONE, ["remote"], False),
    ]


@pytest.mark.asyncio
async def test_the_local_matricxon_is_listed_but_not_removable(db):
    await _save(db)
    state = await OutsideHosts(db, httpx.MockTransport(FakeNodes([]))).read()
    assert [(h.places, h.managed) for h in state.hosts] == [(["local"], True)]
    with pytest.raises(NodeNotAllowedError, match="remote mode first"):
        await OutsideHosts(db, httpx.MockTransport(FakeNodes([]))).remove([state.hosts[0].host], reset=False)


@pytest.mark.asyncio
async def test_cluster_members_are_hidden_and_leftovers_shown(db):
    known = {SEED: {"node_id": "id-a", "advertise_url": ""}, OLD: {"node_id": "id-old", "advertise_url": ""}}
    await _save(db, **_cluster(known_nodes=known))
    nodes = FakeNodes([SEED], members={"id-a": "http://10.0.0.1:1"})
    state = await OutsideHosts(db, httpx.MockTransport(nodes)).read()
    assert (state.cluster, state.known) == (True, True)
    assert [(h.host, h.places) for h in state.hosts] == [(GONE, ["remote"]), (OLD, ["remembered"])]


@pytest.mark.asyncio
async def test_without_a_voter_members_cannot_be_told_apart(db):
    await _save(db, **_cluster())
    state = await OutsideHosts(db, httpx.MockTransport(FakeNodes([]))).read()
    assert (state.known, state.hosts) == (False, [])
    with pytest.raises(NodeNotAllowedError, match="No voter"):
        await OutsideHosts(db, httpx.MockTransport(FakeNodes([]))).remove([GONE], reset=False)


@pytest.mark.asyncio
async def test_batch_remove_forgets_every_place_in_one_save(db):
    known = {SEED: {"node_id": "id-a", "advertise_url": ""}, OLD: {"node_id": "id-old", "advertise_url": ""}}
    await _save(db, **_cluster(known_nodes=known))
    nodes = FakeNodes([SEED], members={"id-a": SEED})
    result = await OutsideHosts(db, httpx.MockTransport(nodes)).remove([GONE, OLD], reset=False)
    assert result.removed == [GONE, OLD] and result.resets == [] and result.state.hosts == []
    saved = await settings_service.get_matricxon_server_config(db)
    assert (saved.mode, saved.remote_hosts, list(saved.known_nodes)) == ("remote", [SEED], [SEED])
    assert matricxon_pool.get_effective_hosts() == [SEED]


@pytest.mark.asyncio
async def test_a_member_or_unknown_host_is_refused_and_nothing_changes(db):
    await _save(db, **_cluster())
    nodes = FakeNodes([SEED], members={"id-a": SEED})
    with pytest.raises(NodeNotAllowedError, match="refresh it"):
        await OutsideHosts(db, httpx.MockTransport(nodes)).remove([GONE, SEED], reset=False)
    assert (await settings_service.get_matricxon_server_config(db)).remote_hosts == [SEED, GONE]


@pytest.mark.asyncio
async def test_the_last_host_is_kept(db):
    await _save(db, mode="remote", remote_hosts=[GONE])
    with pytest.raises(NodeNotAllowedError, match="at least one"):
        await OutsideHosts(db, httpx.MockTransport(FakeNodes([]))).remove([GONE], reset=False)
    assert (await settings_service.get_matricxon_server_config(db)).remote_hosts == [GONE]


@pytest.mark.asyncio
async def test_reset_runs_on_reachable_hosts_only(db):
    await _save(db, mode="remote", remote_hosts=[SEED, GONE, OLD])
    nodes = FakeNodes([SEED, OLD])
    result = await OutsideHosts(db, httpx.MockTransport(nodes)).remove([GONE, OLD], reset=True)
    assert nodes.resets == ["c"]
    assert [(r.host, r.ok, r.reason) for r in result.resets] == [(GONE, False, "not reachable"), (OLD, True, "")]


@pytest.mark.asyncio
async def test_the_route_answers_400_on_a_refusal(db):
    await _save(db, mode="remote", remote_hosts=[SEED])
    with pytest.raises(HTTPException) as caught:
        await cluster_outside.remove_outside_hosts(OutsideRemove(hosts=["http://x:9"]), db=db, _admin=None)
    assert caught.value.status_code == 400
