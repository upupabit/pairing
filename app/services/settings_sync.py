"""Keeps every pAIring server's in-memory settings in step when several machines share one database: a save writes a
new random token to the `settings_version` row (server_pool_broadcast.broadcast_refresh, after the save's commit);
each server checks the row every few seconds and, when it changed, reloads the same caches its internal-refresh
endpoints do (engine, llama.cpp, Matricxon, stable-diffusion.cpp hosts, connectors). The loopback broadcast still
refreshes this machine's other instances at once; this reaches the rest within POLL_SECONDS.

A token, not a counter: no atomic increment needed (the value column is JSON), and any change means "reload".
"""

import asyncio
import logging
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.app_setting import SYSTEM_OWNER_ID, AppSetting
from app.services import (
    connector_config_cache,
    engine_service,
    image_engine_service,
    llamacpp_pool,
    matricxon_pool,
    sdcpp_pool,
    settings_service,
)

logger = logging.getLogger("llama_chat")

SETTINGS_VERSION_KEY = "settings_version"


class SettingsSync:
    POLL_SECONDS = 5.0

    def __init__(self, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal) -> None:
        self._session_factory = session_factory
        self._seen: str | None = None
        self._looked = False
        self._task: asyncio.Task | None = None

    async def bump(self) -> None:
        """After a committed save: other servers reload within POLL_SECONDS; this one already applied it."""
        token = uuid.uuid4().hex
        async with self._session_factory() as db:
            row = await db.get(AppSetting, (SYSTEM_OWNER_ID, SETTINGS_VERSION_KEY))
            if row is None:
                db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=SETTINGS_VERSION_KEY, value=token))
            else:
                row.value = token
            await db.commit()
        self._seen, self._looked = token, True

    async def check(self) -> bool:
        """Reloads the caches if another server saved since the last check. The first check only notes the version:
        startup has just loaded everything."""
        async with self._session_factory() as db:
            row = await db.get(AppSetting, (SYSTEM_OWNER_ID, SETTINGS_VERSION_KEY))
            version = row.value if row is not None else None
            first, self._looked = not self._looked, True
            if first or version == self._seen:
                self._seen = version
                return False
            self._seen = version
            await self._reload(db)
        logger.info("Settings changed on another server: reloaded engine, host and connector settings.")
        return True

    @staticmethod
    async def _reload(db: AsyncSession) -> None:
        await engine_service.load_cache_from_db(db)
        llamacpp_pool.refresh_from_config(await settings_service.get_llamacpp_server_config(db))
        matricxon_pool.refresh_from_config(await settings_service.get_matricxon_server_config(db))
        sdcpp_pool.refresh_from_config(await image_engine_service.get_sdcpp_config(db))
        await connector_config_cache.load_cache_from_db(db)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.check()
            except Exception:  # a DB hiccup must not stop later checks
                logger.exception("Settings version check failed")
            await asyncio.sleep(self.POLL_SECONDS)


settings_sync = SettingsSync()
