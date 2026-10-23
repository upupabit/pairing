"""Builds the Stats live workflow snapshot: this instance's reply stages (live_workflow_bus) plus every
Matricxon node's running replies (matricxon_live_poller). Streamed as SSE while the view is open; nothing is
polled when no one watches. Each frame is built once and shared by every viewer; a large cluster is summarised
(workflow_live_summary.py).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

from app.schemas.workflow_live import WorkflowLiveSnapshot
from app.services import engine_service
from app.services.live_workflow_bus import LiveWorkflowBus, live_workflow
from app.services.matricxon_live_poller import MatricxonLivePoller, matricxon_live_poller
from app.services.workflow_history import WorkflowHistory, workflow_history
from app.services.workflow_live_summary import LiveSummary


class WorkflowLiveService:
    INTERVAL_SECONDS = 0.3
    IDLE_INTERVAL_SECONDS = 2.0  # another engine is active: only re-check the engine

    def __init__(
        self,
        bus: LiveWorkflowBus = live_workflow,
        poller: MatricxonLivePoller = matricxon_live_poller,
        engine: Callable[[], str] = engine_service.current_engine,
        history: WorkflowHistory = workflow_history,
    ) -> None:
        self._bus = bus
        self._poller = poller
        self._engine = engine
        self.history = history
        self._recorded_poll: float | None = None
        self._lock = asyncio.Lock()
        self._frame: tuple[float, str, bool] | None = None  # (built at, SSE frame, live)

    async def snapshot(self) -> WorkflowLiveSnapshot:
        engine = self._engine()
        if engine != "matricxon":
            return WorkflowLiveSnapshot(engine=engine, live=False)
        engine_requests, engine_error = await self._poller.requests()
        all_runs, usual_ms = self._bus.views(), self._bus.usual_ms()
        await self._record(engine_requests, all_runs, usual_ms)
        runs, engine_requests, crowd = LiveSummary(all_runs, engine_requests).split()
        return WorkflowLiveSnapshot(
            engine=engine,
            live=True,
            runs=runs,
            usual_ms=usual_ms,
            engine_requests=engine_requests,
            engine_node_count=len(self._poller.nodes),
            engine_error=engine_error,
            crowd=crowd,
        )

    async def _record(self, requests: list, runs: list, usual_ms: dict[str, float]) -> None:
        """Adds each new poll to the analysis history (Stats > Workflow analysis)."""
        polled_at = getattr(self._poller, "polled_at", None)
        if polled_at is None or polled_at == self._recorded_poll:
            return
        self._recorded_poll = polled_at
        self.history.record(self._poller.nodes, self._poller.unreachable, requests, runs, usual_ms)
        await self.history.save_if_due()

    async def frame(self) -> tuple[str, bool]:
        """(the current SSE frame, live), rebuilt at most once per interval whatever the number of viewers."""
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._frame is None or now - self._frame[0] >= self.INTERVAL_SECONDS:
                snapshot = await self.snapshot()
                self._frame = (now, f"data: {json.dumps(snapshot.model_dump())}\n\n", snapshot.live)
            return self._frame[1], self._frame[2]

    async def events(self) -> AsyncIterator[str]:
        """SSE frames until the client goes away (the response then closes this generator)."""
        while True:
            frame, live = await self.frame()
            yield frame
            await asyncio.sleep(self.INTERVAL_SECONDS if live else self.IDLE_INTERVAL_SECONDS)


workflow_live_service = WorkflowLiveService()
