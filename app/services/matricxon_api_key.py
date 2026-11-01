"""The API key pAIring sends to Matricxon (MATRICXON_API_KEYS on the servers). Set on the Inference engines panel, or
on the Cluster page in cluster mode. Each server gets it at once (matricxon_key_push.py, no restart); pAIring stores it
encrypted only after every server took it."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import MatricxonApiKeyState
from app.services import engine_service, matricxon_pool, matricxon_process, server_pool_broadcast, settings_service
from app.services.matricxon_key_push import MatricxonKeyPush

logger = logging.getLogger("llama_chat")


class ApiKeyOnClusterPageError(Exception):
    """In cluster mode the key belongs to the Cluster page, with the other settings every node shares."""


class MatricxonApiKey:
    def __init__(self, db: AsyncSession, push: MatricxonKeyPush | None = None) -> None:
        self._db = db
        self._push = push or MatricxonKeyPush()

    async def state(self) -> MatricxonApiKeyState:
        config = await settings_service.get_matricxon_server_config(self._db)
        return MatricxonApiKeyState(set=bool(config.api_key), cluster=config.cluster_role != "off")

    async def set(self, key: str, from_cluster_page: bool = False) -> MatricxonApiKeyState:
        """Gives every Matricxon pAIring uses the key ("" removes it), then saves it here.
        Raises NodeNotAllowedError (nothing changed) when a server is down or refuses."""
        config = await settings_service.get_matricxon_server_config(self._db)
        if config.cluster_role != "off" and not from_cluster_page:
            raise ApiKeyOnClusterPageError("Cluster mode is on: set the API key on the Cluster page.")
        old = config.api_key or ""
        if key != old:
            await self._push.push(matricxon_pool.get_effective_hosts(), key, old)
        config.api_key = key or None
        await settings_service.set_matricxon_server_config(self._db, config)
        matricxon_process.write_env_file(config)
        if await engine_service.get_active_engine(self._db) == "matricxon":
            matricxon_pool.refresh_from_config(config)
            failures = await server_pool_broadcast.broadcast_refresh("/api/settings/matricxon/internal-refresh")
            if failures:
                logger.warning("Some instances did not pick up the new Matricxon API key: %s", "; ".join(failures))
        logger.info(
            "matricxon: API key %s on %d server(s)",
            "set" if key else "removed",
            len(matricxon_pool.get_effective_hosts()),
        )
        return await self.state()
