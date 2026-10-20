"""Polls each llama-server's `GET /models` and appends a snapshot row per loaded model (read back by
model_snapshot_service for the Telemetry page), the counterpart of Matricxon's /api/ps poller.

Primary-gated (startup_service): loaded models are host-level state. Local sizes come from the shared store;
llama-server reports no memory figure, and a sleeping model (idle unload) holds none, so it isn't listed.
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.database import AsyncSessionLocal
from app.models import ModelSnapshot
from app.services import llamacpp_admin, llamacpp_pool, model_snapshot_service
from app.services.llamacpp_models import LlamaCppModelName

logger = logging.getLogger("llama_chat")

POLL_INTERVAL_SECONDS = model_snapshot_service.POLL_INTERVAL_SECONDS
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_background_poller_tasks: set[asyncio.Task] = set()


class LlamaCppPsPoller:
    async def poll_once(self) -> None:
        sizes = await self._local_sizes() if llamacpp_pool.is_local() else {}
        snapshots: list[ModelSnapshot] = []
        for host in llamacpp_pool.get_effective_hosts():
            try:
                snapshots.extend(await self._poll_host(host, sizes))
            except httpx.HTTPError as exc:
                logger.warning("Could not poll /models on %s: %s", host, exc)
        if not snapshots:
            return
        async with AsyncSessionLocal() as db:
            db.add_all(snapshots)
            await db.commit()

    @staticmethod
    async def _local_sizes() -> dict[str, int]:
        return {model.tag: model.size_bytes for model in (await llamacpp_admin.store()).models()}

    @staticmethod
    async def _poll_host(host: str, sizes: dict[str, int]) -> list[ModelSnapshot]:
        polled_at = datetime.now(UTC)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{host}/models")
            resp.raise_for_status()
        rows = []
        for entry in resp.json().get("data", []):
            if (entry.get("status") or {}).get("value") != "loaded":
                continue
            name = LlamaCppModelName.from_router(entry["id"])
            rows.append(
                ModelSnapshot(
                    engine="llamacpp",
                    host=host,
                    model_name=name,
                    size_bytes=sizes.get(name),
                    size_vram_bytes=None,
                    expires_at=None,
                    polled_at=polled_at,
                )
            )
        return rows

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                # A bad poll (e.g. a transient DB error) must never end the loop.
                logger.exception("llama.cpp /models poll failed.")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def start_llamacpp_ps_poller() -> None:
    """Called once from startup_service (primary only); keeps a strong reference to the task."""
    task = asyncio.create_task(LlamaCppPsPoller().run())
    _background_poller_tasks.add(task)
    task.add_done_callback(_background_poller_tasks.discard)
