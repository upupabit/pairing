"""Tests for services/live_workflow_bus.py: per-reply stage timing for the Stats live workflow view."""

import asyncio

import pytest

from app.services import live_workflow_bus
from app.services.live_workflow_bus import LiveWorkflowBus


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def bus(clock: FakeClock) -> LiveWorkflowBus:
    token = live_workflow_bus._current.set(None)
    yield LiveWorkflowBus(clock, engine=lambda: "matricxon")
    live_workflow_bus._current.reset(token)


def test_nothing_is_tracked_for_another_engine(clock: FakeClock) -> None:
    bus = LiveWorkflowBus(clock, engine=lambda: "llamacpp")

    assert bus.begin("m") is None
    bus.enter("rag_embed")
    assert bus.views() == []


def test_times_a_stage_and_shows_it_active_while_running(bus: LiveWorkflowBus, clock: FakeClock) -> None:
    bus.begin("m")
    bus.enter("rag_embed")
    clock.now += 0.25
    running = bus.views()[0].nodes["rag_embed"]
    clock.now += 0.25
    bus.exit("rag_embed")

    done = bus.views()[0].nodes["rag_embed"]

    assert running.active and running.elapsed_ms == 250
    assert not done.active and done.elapsed_ms == 500 and done.count == 1


def test_nested_enters_count_once(bus: LiveWorkflowBus, clock: FakeClock) -> None:
    bus.begin("m")
    bus.enter("ml_engine_server")
    bus.enter("ml_engine_server")
    clock.now += 1
    bus.exit("ml_engine_server")
    assert bus.views()[0].nodes["ml_engine_server"].active
    bus.exit("ml_engine_server")

    assert bus.views()[0].nodes["ml_engine_server"].count == 1


def test_pulses_count_chunks(bus: LiveWorkflowBus) -> None:
    bus.begin("m")
    for _ in range(3):
        bus.pulse("broadcast_publish")

    view = bus.views()[0]

    assert view.chunks == 3
    assert view.nodes["broadcast_publish"].count == 3


def test_usual_time_needs_enough_samples(bus: LiveWorkflowBus) -> None:
    for seconds in (0.1, 0.2, 0.3, 0.4):
        bus.record("rag_rerank", seconds)
    assert bus.usual_ms() == {}

    for seconds in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        bus.record("rag_rerank", seconds)

    assert bus.usual_ms() == {"rag_rerank": 1000.0}


def test_end_stops_running_stages_and_ignores_later_marks(bus: LiveWorkflowBus) -> None:
    run = bus.begin("m")
    bus.enter("run_generation_task")
    run.end()
    bus.enter("inference_client_stream")
    bus.pulse("relay_back")

    view = bus.views()[0]

    assert view.done
    assert not view.nodes["run_generation_task"].active
    assert set(view.nodes) == {"run_generation_task"}


def test_a_quiet_run_without_generation_is_ended(bus: LiveWorkflowBus, clock: FakeClock) -> None:
    bus.begin("m")
    clock.now += LiveWorkflowBus.STALE_SECONDS + 1

    assert bus.views()[0].done


def test_finished_runs_are_dropped_after_a_while(bus: LiveWorkflowBus, clock: FakeClock) -> None:
    bus.begin("m").end()
    clock.now += LiveWorkflowBus.KEEP_FINISHED_SECONDS + 1

    assert bus.views() == []


@pytest.mark.asyncio
async def test_a_detached_task_keeps_the_run_and_track_ends_it(bus: LiveWorkflowBus) -> None:
    run = bus.begin("m")
    bus.bind_request("msg-1")

    async def generation() -> None:
        bus.pulse("broadcast_publish")

    await asyncio.create_task(bus.track(generation(), "run_generation_task"))

    view = bus.views()[0]
    assert run.request_id == "msg-1"
    assert view.done and view.chunks == 1
    assert view.nodes["run_generation_task"].count == 1


def test_keeps_only_the_latest_finished_runs(bus: LiveWorkflowBus, clock: FakeClock) -> None:
    running = bus.begin("m")
    for _ in range(LiveWorkflowBus.MAX_FINISHED + 5):
        clock.now += 0.1
        bus.begin("m").end()

    views = bus.views()

    assert len(views) == LiveWorkflowBus.MAX_FINISHED + 1
    assert running.run_id in {v.run_id for v in views}


def test_old_runs_are_dropped_even_when_no_one_watches(bus: LiveWorkflowBus, clock: FakeClock) -> None:
    bus.begin("m").end()
    clock.now += LiveWorkflowBus.KEEP_FINISHED_SECONDS + 1

    bus.begin("m")

    assert len(bus._runs) == 1
