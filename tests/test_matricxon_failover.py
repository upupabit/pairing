"""Matricxon cluster failover beyond connection errors: an error reply another node may not give (out of memory, a
failed load, a model the node lacks) is retried on the next node, without the cooldown a down node gets
(server_pool.HostPool retry_on, matricxon_errors). Covers chat's pool path, embeddings and reranking."""

import httpx
import pytest

from app.services import matricxon_client, matricxon_pool
from app.services.matricxon_errors import MatricxonError, MatricxonHostError, MatricxonReply
from app.services.matricxon_rerank import MatricxonRerankClient
from app.services.server_pool import HostPool

A, B = "http://node-a:8420", "http://node-b:8420"


@pytest.mark.parametrize(("status", "retryable"), [(503, True), (500, True), (404, True), (400, False), (409, False)])
def test_only_node_specific_error_replies_are_retried(status: int, retryable: bool) -> None:
    error = MatricxonReply.error(b'{"error": "not enough memory to load m"}', status)

    assert isinstance(error, MatricxonError)
    assert isinstance(error, MatricxonHostError) is retryable
    assert str(error) == "not enough memory to load m"


@pytest.mark.asyncio
async def test_an_error_reply_moves_to_the_next_node_without_a_cooldown() -> None:
    pool = HostPool()
    pool.set_hosts([A, B])
    order: list[str] = []

    async def stream(host: str):
        order.append(host)
        if len(order) == 1:
            raise MatricxonHostError("not enough memory")
        yield f"hi from {host}"

    chunks = [c async for c in pool.stream_with_failover(stream, retry_on=(MatricxonHostError,))]

    assert chunks == [f"hi from {order[1]}"] and len(set(order)) == 2
    assert pool.healthy_hosts() == [A, B]


@pytest.mark.asyncio
async def test_a_down_node_still_gets_the_cooldown_and_a_bad_request_is_not_retried() -> None:
    pool = HostPool()
    pool.set_hosts([A, B])
    tried: list[str] = []

    async def down_then_ok(host: str) -> str:
        tried.append(host)
        if len(tried) == 1:
            raise httpx.ConnectError("refused")
        return "ok"

    assert await pool.call_with_failover(down_then_ok, retry_on=(MatricxonHostError,)) == "ok"
    assert pool.healthy_hosts() == [tried[1]]

    async def bad_request(host: str) -> str:
        raise MatricxonError("prompt too long")

    with pytest.raises(MatricxonError, match="prompt too long"):
        await pool.call_with_failover(bad_request, retry_on=(MatricxonHostError,))


@pytest.mark.asyncio
async def test_nothing_switches_nodes_after_the_first_chunk() -> None:
    pool = HostPool()
    pool.set_hosts([A, B])

    async def fails_mid_reply(host: str):
        yield "partial"
        raise MatricxonHostError("crashed")

    with pytest.raises(MatricxonHostError):
        _ = [c async for c in pool.stream_with_failover(fails_mid_reply, retry_on=(MatricxonHostError,))]


class _Reply:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code = status
        self.is_error = status >= 400
        self._body = body
        self.content = str(body).replace("'", '"').encode()

    def json(self) -> dict:
        return self._body


class _NodeAOutOfMemory:
    """node-a refuses (503), node-b answers: what a cluster node short of RAM does."""

    def __init__(self, ok_body: dict, seen: list[str]) -> None:
        self._ok_body = ok_body
        self._seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url: str, json: dict) -> _Reply:
        self._seen.append(url)
        if url.startswith(A):
            return _Reply(503, {"error": "not enough memory"})
        return _Reply(200, self._ok_body)


@pytest.fixture
def two_nodes(monkeypatch) -> list[str]:
    pool = HostPool()
    pool.set_hosts([A, B])
    monkeypatch.setattr(matricxon_pool, "_pool", pool)
    pool._states[B].in_flight = 1  # node-a is picked first
    return []


@pytest.mark.asyncio
async def test_embeddings_fail_over_to_the_node_that_can_answer(monkeypatch, two_nodes) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _NodeAOutOfMemory({"embedding": [0.5]}, two_nodes))

    assert await matricxon_client.embed("text", "embed:latest") == [0.5]
    assert [u.split("/api")[0] for u in two_nodes] == [A, B]


@pytest.mark.asyncio
async def test_reranking_fails_over_to_the_node_that_can_answer(monkeypatch, two_nodes) -> None:
    body = {"results": [{"index": 0, "relevance_score": 0.7}]}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _NodeAOutOfMemory(body, two_nodes))

    assert await MatricxonRerankClient().rerank("q", ["d0"], "rr:latest") == [0.7]
    assert [u.split("/api")[0] for u in two_nodes] == [A, B]
