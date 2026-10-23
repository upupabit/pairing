"""Tests for services/workflow_live_summary.py and the large-cluster parts of the live view's poller and service."""

import json

import httpx
import pytest

from app.schemas.workflow_live import EngineRequestView, LiveNodeTiming, LiveRunView
from app.services.live_workflow_bus import LiveWorkflowBus
from app.services.matricxon_live_poller import MatricxonLivePoller
from app.services.workflow_live_service import WorkflowLiveService
from app.services.workflow_live_summary import LiveSummary


def _request(i: int, phase: str = "decode", tps: float = 10.0, usual: float | None = 10.0) -> EngineRequestView:
    return EngineRequestView(
        host=f"http://n{i % 7}", request_id=f"r{i}", model="m", phase=phase, elapsed_seconds=float(i),
        tokens_per_second=tps, usual_tokens_per_second=usual,
    )  # fmt: skip


def _run(i: int, active: str = "rag_rerank") -> LiveRunView:
    nodes = {active: LiveNodeTiming(active=True, elapsed_ms=10.0, count=0)}
    return LiveRunView(
        run_id=f"run{i}", request_id=f"r{i}", model="m", elapsed_ms=1.0, done=False, chunks=0, nodes=nodes
    )


def test_a_small_cluster_is_sent_unchanged() -> None:
    runs, requests, crowd = LiveSummary([_run(1)], [_request(1), _request(2)]).split()

    assert [r.run_id for r in runs] == ["run1"] and len(requests) == 2 and crowd is None


def test_a_large_cluster_keeps_this_instances_chats_and_the_slowest() -> None:
    requests = [_request(i) for i in range(100)] + [_request(500, tps=2.0)]
    runs = [_run(1), _run(2)]

    kept_runs, kept, crowd = LiveSummary(runs, requests).split()

    ids = [r.request_id for r in kept]
    assert len(ids) == LiveSummary.DETAILED
    assert ids[:3] == ["r1", "r2", "r500"]  # this instance's chats, then the slowest
    assert [r.run_id for r in kept_runs] == ["run1", "run2"]
    assert crowd.running == 101 - LiveSummary.DETAILED
    assert crowd.engine["decode"].replies == crowd.running
    assert crowd.busy_nodes == 7


def test_the_crowd_counts_app_steps_of_chats_left_out() -> None:
    runs = [_run(i) for i in range(30)]

    _, _, crowd = LiveSummary(runs, []).split()

    assert crowd.app == {"rag_rerank": 30 - LiveSummary.DETAILED}


@pytest.mark.asyncio
async def test_a_counted_chat_is_not_counted_twice_at_the_engine() -> None:
    runs = [_run(i, active="ml_engine_server") for i in range(30)]
    requests = [_request(i) for i in range(30)]

    _, _, crowd = LiveSummary(runs, requests).split()

    assert "ml_engine_server" not in crowd.app
    assert crowd.app["broadcast_publish"] == crowd.engine["decode"].replies == 30 - LiveSummary.DETAILED


@pytest.mark.asyncio
async def test_poller_rests_a_failed_node_and_repeats_its_error() -> None:
    calls: list[str] = []

    async def fetch(host: str) -> list[dict]:
        calls.append(host)
        raise httpx.ConnectError("down")

    now = [0.0]
    poller = MatricxonLivePoller(fetch, lambda: ["http://a"], lambda: now[0])
    _, first = await poller.requests()
    now[0] = 5.0
    _, second = await poller.requests()
    now[0] = 11.0
    await poller.requests()

    assert first == second == "http://a: down"
    assert calls == ["http://a", "http://a"]  # not read again until RETRY_SECONDS passed


@pytest.mark.asyncio
async def test_poller_reads_a_large_cluster_less_often() -> None:
    hosts = [f"http://n{i}" for i in range(1000)]
    calls = []

    async def fetch(host: str) -> list[dict]:
        calls.append(host)
        return []

    now = [0.0]
    poller = MatricxonLivePoller(fetch, lambda: hosts, lambda: now[0])
    await poller.requests()
    now[0] = 1.0
    await poller.requests()
    now[0] = 2.0
    await poller.requests()

    assert len(calls) == 2000  # skipped at 1 s, read again at 2 s


class CountingPoller:
    nodes: list[str] = []

    def __init__(self) -> None:
        self.calls = 0

    async def requests(self) -> tuple[list, None]:
        self.calls += 1
        return [], None


@pytest.mark.asyncio
async def test_viewers_share_one_frame() -> None:
    poller = CountingPoller()
    service = WorkflowLiveService(LiveWorkflowBus(engine=lambda: "matricxon"), poller, lambda: "matricxon")

    frames = [await anext(service.events()) for _ in range(3)]

    assert poller.calls == 1
    assert json.loads(frames[0].removeprefix("data: "))["crowd"] is None
