"""The API key pAIring sends to Matricxon (MATRICXON_API_KEYS on the servers). Stored encrypted in the Matricxon
config; local mode writes it to Matricxon's .env too, so the local server enforces it after a restart."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import MatricxonApiKeyState
from app.services import engine_service, matricxon_pool, matricxon_process, server_pool_broadcast, settings_service

logger = logging.getLogger("llama_chat")


class MatricxonApiKey:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def state(self, restart_needed: bool = False) -> MatricxonApiKeyState:
        config = await settings_service.get_matricxon_server_config(self._db)
        return MatricxonApiKeyState(
            set=bool(config.api_key), local=config.mode == "local", restart_needed=restart_needed
        )

    async def set(self, key: str) -> MatricxonApiKeyState:
        """Saves the key ("" removes it) and starts sending it at once."""
        config = await settings_service.get_matricxon_server_config(self._db)
        changed = (config.api_key or "") != key
        config.api_key = key or None
        await settings_service.set_matricxon_server_config(self._db, config)
        matricxon_process.write_env_file(config)
        if await engine_service.get_active_engine(self._db) == "matricxon":
            matricxon_pool.refresh_from_config(config)
            failures = await server_pool_broadcast.broadcast_refresh("/api/settings/matricxon/internal-refresh")
            if failures:
                logger.warning("Some instances did not pick up the new Matricxon API key: %s", "; ".join(failures))
        running = config.mode == "local" and (await matricxon_process.get_status(config.project_dir)).running
        return await self.state(restart_needed=changed and running)
