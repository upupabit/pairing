"""Every process, every ServerRegistry.HEARTBEAT_SECONDS: its heartbeat row; a primary's part in an
"Update all"; and, on the leader, clearing offline servers' replies and advancing the rollout. Nothing on
SQLite, which only one machine can use."""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import IS_PRIMARY
from app.database import AsyncSessionLocal
from app.services.db_clock import shared_database
from app.services.leader_lease import leader_lease
from app.services.rolling_update import RollingUpdate, rolling_update
from app.services.server_facts import ServerFacts, server_facts
from app.services.server_registry import ServerRegistry, server_registry

logger = logging.getLogger("llama_chat")


class ServerHeartbeat:
    def __init__(
        self,
        registry: ServerRegistry = server_registry,
        rollout: RollingUpdate = rolling_update,
        is_primary: bool = IS_PRIMARY,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
        shared: Callable[[AsyncSession], bool] = shared_database,
        facts: ServerFacts = server_facts,
    ) -> None:
        self._shared = shared
        self._facts = facts
        self._registry = registry
        self._rollout = rollout
        self._is_primary = is_primary
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None

    async def tick(self) -> None:
        async with self._session_factory() as db:
            if not self._shared(db):
                return  # SQLite: one machine, nothing to coordinate and no writes
            details = self._facts.report()
            if progress := self._rollout.progress():
                details["update_progress"] = progress
            await self._registry.heartbeat(db, details)
            if self._is_primary:
                await self._rollout.server_step(db)
            if leader_lease.is_leader:
                await self._registry.sweep_offline(db)
                await self._rollout.leader_step(db)
                await self._facts.refresh_markers(db)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - a database hiccup must not end the heartbeat
                logger.exception("Server heartbeat failed.")
            await asyncio.sleep(self._registry.HEARTBEAT_SECONDS)


server_heartbeat = ServerHeartbeat()
