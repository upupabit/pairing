"""Live stage timing of chat replies for Stats > Visual chat workflow (Matricxon engine only).

Each reply gets a LiveRun, carried by a ContextVar so detached tasks (reply_generation_service) inherit it;
call sites mark workflow nodes (ids from workflow_diagram_data.js) with `stage`/`enter`/`exit`/`pulse`, all
no-ops when no run is active. In-process: it sees the replies this instance handles.
"""

import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar

from app.schemas.workflow_live import LiveNodeTiming, LiveRunView
from app.services import engine_service

_current: ContextVar["LiveRun | None"] = ContextVar("live_workflow_run", default=None)


class _NodeTiming:
    __slots__ = ("active_since", "total", "count", "depth")

    def __init__(self) -> None:
        self.active_since: float | None = None
        self.total = 0.0
        self.count = 0
        self.depth = 0


class LiveRun:
    def __init__(self, bus: "LiveWorkflowBus", model: str, clock: Callable[[], float]) -> None:
        self.run_id = uuid.uuid4().hex[:12]
        self.model = model
        self.request_id: str | None = None
        self._bus = bus
        self._clock = clock
        self.started = clock()
        self.last_activity = self.started
        self.finished_at: float | None = None
        self.chunks = 0
        self._nodes: dict[str, _NodeTiming] = {}

    def enter(self, node: str) -> None:
        if self.finished_at is not None:  # e.g. a smart-title task that inherited the context
            return
        timing = self._nodes.setdefault(node, _NodeTiming())
        timing.depth += 1
        if timing.depth == 1:
            timing.active_since = self._clock()
        self.last_activity = self._clock()

    def exit(self, node: str) -> None:
        timing = self._nodes.get(node)
        if timing is None or timing.depth == 0:
            return
        timing.depth -= 1
        if timing.depth or timing.active_since is None:
            return
        seconds = self._clock() - timing.active_since
        timing.total += seconds
        timing.count += 1
        timing.active_since = None
        self.last_activity = self._clock()
        self._bus.record(node, seconds)

    def pulse(self, node: str) -> None:
        """A point event (a chunk relayed, a reply done): counted, no duration."""
        if self.finished_at is not None:
            return
        timing = self._nodes.setdefault(node, _NodeTiming())
        timing.count += 1
        self.last_activity = self._clock()
        if node == "broadcast_publish":
            self.chunks += 1

    def bind_request(self, request_id: str) -> None:
        """The engine-side id (the assistant message id) a generation runs under."""
        self.request_id = request_id

    def end(self) -> None:
        if self.finished_at is not None:
            return
        for node, timing in self._nodes.items():
            while timing.depth:
                self.exit(node)
        self.finished_at = self._clock()

    def view(self) -> LiveRunView:
        now = self._clock()
        nodes = {
            node: LiveNodeTiming(
                active=t.active_since is not None,
                elapsed_ms=round(1000 * (t.total + (now - t.active_since if t.active_since is not None else 0)), 1),
                count=t.count,
            )
            for node, t in self._nodes.items()
        }
        return LiveRunView(
            run_id=self.run_id,
            request_id=self.request_id,
            model=self.model,
            elapsed_ms=round(1000 * ((self.finished_at or now) - self.started), 1),
            done=self.finished_at is not None,
            chunks=self.chunks,
            nodes=nodes,
        )


class LiveWorkflowBus:
    KEEP_FINISHED_SECONDS = 120.0
    MAX_FINISHED = 30  # on a busy server, only the latest finished runs are kept
    STALE_SECONDS = 60.0  # a run with no generation and no activity this long is ended
    SAMPLES = 50
    MIN_SAMPLES = 5

    def __init__(self, clock: Callable[[], float] = time.monotonic, engine: Callable[[], str] | None = None) -> None:
        self._clock = clock
        self._engine = engine or engine_service.current_engine
        self._runs: dict[str, LiveRun] = {}
        self._samples: dict[str, deque[float]] = {}

    def begin(self, model: str) -> LiveRun | None:
        """Starts a run for this context; None (nothing tracked) unless the engine is Matricxon."""
        if self._engine() != "matricxon":
            return None
        run = LiveRun(self, model, self._clock)
        self._runs[run.run_id] = run
        _current.set(run)
        return run

    @staticmethod
    def current() -> LiveRun | None:
        return _current.get()

    def enter(self, *nodes: str) -> None:
        if run := _current.get():
            for node in nodes:
                run.enter(node)

    def exit(self, *nodes: str) -> None:
        if run := _current.get():
            for node in nodes:
                run.exit(node)

    def pulse(self, node: str) -> None:
        if run := _current.get():
            run.pulse(node)

    def bind_request(self, request_id: str) -> None:
        if run := _current.get():
            run.bind_request(request_id)

    @asynccontextmanager
    async def stage(self, *nodes: str) -> AsyncIterator[None]:
        self.enter(*nodes)
        try:
            yield
        finally:
            self.exit(*nodes)

    async def track(self, work: Awaitable[None], node: str) -> None:
        """Runs a reply's detached generation as `node`; the run ends with it."""
        self.enter(node)
        try:
            await work
        finally:
            if run := _current.get():
                run.end()

    def record(self, node: str, seconds: float) -> None:
        self._samples.setdefault(node, deque(maxlen=self.SAMPLES)).append(seconds)

    def usual_ms(self) -> dict[str, float]:
        """Each node's p90 duration, once it has enough samples."""
        usual = {}
        for node, samples in self._samples.items():
            if len(samples) >= self.MIN_SAMPLES:
                ordered = sorted(samples)
                usual[node] = round(1000 * ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 1)
        return usual

    def views(self) -> list[LiveRunView]:
        now = self._clock()
        for run_id, run in list(self._runs.items()):
            if run.finished_at is None and run.request_id is None and now - run.last_activity > self.STALE_SECONDS:
                run.end()
            if run.finished_at is not None and now - run.finished_at > self.KEEP_FINISHED_SECONDS:
                del self._runs[run_id]
        finished = sorted((r for r in self._runs.values() if r.finished_at is not None), key=lambda r: r.finished_at)
        for run in finished[: max(len(finished) - self.MAX_FINISHED, 0)]:
            del self._runs[run.run_id]
        return [run.view() for run in self._runs.values()]


live_workflow = LiveWorkflowBus()
