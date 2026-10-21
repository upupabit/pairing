"""Builds the Stats live workflow snapshot: this instance's reply stages (live_workflow_bus) plus every
Matricxon node's running replies (matricxon_live_poller). Streamed as SSE while the view is open; nothing is
polled when no one watches.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

from app.schemas.workflow_live import WorkflowLiveSnapshot
from app.services import engine_service
from app.services.live_workflow_bus import LiveWorkflowBus, live_workflow
from app.services.matricxon_live_poller import MatricxonLivePoller, matricxon_live_poller


class WorkflowLiveService:
    INTERVAL_SECONDS = 0.3
    IDLE_INTERVAL_SECONDS = 2.0  # another engine is active: only re-check the engine

    def __init__(
        self,
        bus: LiveWorkflowBus = live_workflow,
        poller: MatricxonLivePoller = matricxon_live_poller,
        engine: Callable[[], str] = engine_service.current_engine,
    ) -> None:
        self._bus = bus
        self._poller = poller
        self._engine = engine

    async def snapshot(self) -> WorkflowLiveSnapshot:
        engine = self._engine()
        if engine != "matricxon":
            return WorkflowLiveSnapshot(engine=engine, live=False)
        engine_requests, engine_error = await self._poller.requests()
        return WorkflowLiveSnapshot(
            engine=engine,
            live=True,
            runs=self._bus.views(),
            usual_ms=self._bus.usual_ms(),
            engine_requests=engine_requests,
            engine_error=engine_error,
        )

    async def events(self) -> AsyncIterator[str]:
        """SSE frames until the client goes away (the response then closes this generator)."""
        while True:
            snapshot = await self.snapshot()
            yield f"data: {json.dumps(snapshot.model_dump())}\n\n"
            await asyncio.sleep(self.INTERVAL_SECONDS if snapshot.live else self.IDLE_INTERVAL_SECONDS)
