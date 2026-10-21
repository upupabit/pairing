"""Tests for the Stats live workflow: services/matricxon_live_poller.py, services/workflow_live_service.py and
routers/workflow_live.py."""

import json

import httpx
import pytest

from app.routers import workflow_live
from app.schemas.workflow_live import WorkflowLiveSnapshot
from app.services.live_workflow_bus import LiveWorkflowBus
from app.services.matricxon_live_poller import MatricxonLivePoller
from app.services.workflow_live_service import WorkflowLiveService


class FakeClock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


def _entry(request_id: str, phase: str = "decode", **extra: object) -> dict:
    return {"request_id": request_id, "model": "m", "phase": phase, "elapsed_seconds": 1.0, **extra}


class FakeFetch:
    def __init__(self, replies: dict[str, object]) -> None:
        self.replies = replies
        self.calls = 0

    async def __call__(self, host: str) -> list[dict]:
        self.calls += 1
        reply = self.replies[host]
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.mark.asyncio
async def test_poller_reads_every_host_and_caches_briefly() -> None:
    clock = FakeClock()
    fetch = FakeFetch({"http://a": [_entry("r1")], "http://b": [_entry("r2", phase="prefill")]})
    poller = MatricxonLivePoller(fetch, lambda: ["http://a", "http://b"], clock)

    views, error = await poller.requests()
    await poller.requests()

    assert [(v.host, v.request_id) for v in views] == [("http://a", "r1"), ("http://b", "r2")]
    assert error is None
    assert fetch.calls == 2
    clock.now += 1
    await poller.requests()
    assert fetch.calls == 4


@pytest.mark.asyncio
async def test_poller_explains_a_node_without_the_live_route() -> None:
    response = httpx.Response(404, request=httpx.Request("GET", "http://a/api/live"))
    fetch = FakeFetch({"http://a": httpx.HTTPStatusError("404", request=response.request, response=response)})

    views, error = await MatricxonLivePoller(fetch, lambda: ["http://a"], FakeClock()).requests()

    assert views == []
    assert "update Matricxon" in error


@pytest.mark.asyncio
async def test_poller_learns_usual_rates_from_finished_replies() -> None:
    clock = FakeClock()
    done = [
        _entry(f"d{i}", "done", tokens_per_second=10.0 + i, prompt_tokens=200, first_token_seconds=2.0)
        for i in range(3)
    ]
    poller = MatricxonLivePoller(FakeFetch({"http://a": [*done, _entry("live")]}), lambda: ["http://a"], clock)

    await poller.requests()
    clock.now += 1
    views, _ = await poller.requests()

    live = next(v for v in views if v.request_id == "live")
    assert live.usual_tokens_per_second == 11.0
    assert live.usual_prefill_tokens_per_second == 100.0


class FakePoller:
    def __init__(self) -> None:
        self.calls = 0

    async def requests(self) -> tuple[list, str | None]:
        self.calls += 1
        return [], "node down"


@pytest.mark.asyncio
async def test_service_is_idle_for_another_engine() -> None:
    poller = FakePoller()
    service = WorkflowLiveService(LiveWorkflowBus(engine=lambda: "llamacpp"), poller, lambda: "llamacpp")

    snapshot = await service.snapshot()

    assert snapshot.live is False and snapshot.engine == "llamacpp"
    assert poller.calls == 0


@pytest.mark.asyncio
async def test_service_combines_runs_and_engine_state() -> None:
    bus = LiveWorkflowBus(engine=lambda: "matricxon")
    service = WorkflowLiveService(bus, FakePoller(), lambda: "matricxon")

    frame = await anext(service.events())

    payload = json.loads(frame.removeprefix("data: "))
    assert payload["live"] is True
    assert payload["engine_error"] == "node down"
    assert frame.endswith("\n\n")


@pytest.mark.asyncio
async def test_snapshot_route_answers_an_admin(admin_user, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow_live.WorkflowLiveService, "snapshot", _fake_snapshot)

    snapshot = await workflow_live.get_snapshot(_admin=admin_user)

    assert snapshot.engine == "matricxon"


async def _fake_snapshot(self: WorkflowLiveService) -> WorkflowLiveSnapshot:
    return WorkflowLiveSnapshot(engine="matricxon", live=True)
