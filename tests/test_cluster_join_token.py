"""Cluster page > Add a node with the new node's join token (Matricxon's cluster/join_token.py): it is sent as a
header on the provisioning call, and a node that refuses without it gets a message saying where to find it."""

import httpx
import pytest

from app.services.cluster_nodes import JOIN_TOKEN_HEADER, ClusterNodes, NodeNotAllowedError
from tests.test_cluster_nodes import NODE, _configure, _quiet_broadcast, _quorum_ok  # noqa: F401


def _node(seen: list, needs: str | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/cluster/fresh":
            return httpx.Response(200, json={"fresh": True, "reasons": []})
        if request.url.path != "/api/cluster/provision":
            return httpx.Response(404)
        seen.append(request.headers.get(JOIN_TOKEN_HEADER))
        if needs and request.headers.get(JOIN_TOKEN_HEADER) != needs:
            return httpx.Response(403, json={"detail": "this node is new: give its join token"})
        return httpx.Response(200, json={"restarting": True})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_the_join_token_goes_with_the_provisioning_call(db) -> None:
    await _configure(db)
    seen: list = []

    await ClusterNodes(db, _node(seen, needs="tok-123")).add(NODE, join_token=" tok-123 ")

    assert seen == ["tok-123"]


@pytest.mark.asyncio
async def test_a_missing_token_says_where_to_find_it(db) -> None:
    await _configure(db)
    seen: list = []

    with pytest.raises(NodeNotAllowedError, match="join token"):
        await ClusterNodes(db, _node(seen, needs="tok-123")).add(NODE)
    assert seen == [None]
