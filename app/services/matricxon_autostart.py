"""Starts the local Matricxon when pAIring starts, if it is the active engine and isn't running: after a restart, an
update or a reboot it comes back without anyone pressing Start. Runs in the background so the UI is up meanwhile, then
runs the startup work that needs the engine (`then`). Off with MATRICXON_AUTOSTART=false.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.config import IS_PRIMARY, MATRICXON_AUTOSTART
from app.database import AsyncSessionLocal
from app.schemas import MatricxonServerConfig
from app.services import engine_service, http_proxy_service, matricxon_process, settings_service

logger = logging.getLogger("llama_chat")


class MatricxonAutostart:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None  # kept so the task isn't garbage-collected

    async def needed(self) -> tuple[MatricxonServerConfig, str | None] | None:
        """The config and proxy to start with, or None when it isn't ours to start (or already runs)."""
        if not (MATRICXON_AUTOSTART and IS_PRIMARY) or engine_service.current_engine() != "matricxon":
            return None
        async with AsyncSessionLocal() as db:
            config = await settings_service.get_matricxon_server_config(db)
            proxy = (await http_proxy_service.get_http_proxy_config(db)).proxy_url()
        if config.mode != "local" or not matricxon_process.is_installed(config.project_dir):
            return None
        if (await matricxon_process.get_status(config.project_dir)).running:
            return None
        return config, proxy

    def schedule(self, config: MatricxonServerConfig, proxy: str | None, then: Callable[[], Awaitable[None]]) -> None:
        self._task = asyncio.create_task(self.run(config, proxy, then))

    @staticmethod
    async def run(config: MatricxonServerConfig, proxy: str | None, then: Callable[[], Awaitable[None]]) -> None:
        try:
            await matricxon_process.start(config, proxy_url=proxy)
        except (RuntimeError, ValueError) as exc:
            logger.warning("Could not start Matricxon at startup (%s). Start it in Settings > Inference engines.", exc)
            return
        logger.info("Started Matricxon, the active engine, at pAIring startup.")
        await then()


matricxon_autostart = MatricxonAutostart()
