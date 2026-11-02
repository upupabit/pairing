"""Active engine switch while Matricxon cluster mode is on: allowed only once the admin confirms.

The cluster stays on and its nodes keep running; only chats move. Switching back to Matricxon resumes it.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import EngineName
from app.services import engine_service, settings_service
from app.services.engines.registry import registry


class ClusterSwitchUnconfirmedError(Exception):
    """The message is the warning shown to the admin."""


class EngineSwitch:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check(self, target: EngineName, leave_cluster: bool) -> None:
        """Raises ClusterSwitchUnconfirmedError when leaving a Matricxon cluster without `leave_cluster`."""
        if leave_cluster or target == "matricxon":
            return
        if await engine_service.get_active_engine(self._db) != "matricxon":
            return
        config = await settings_service.get_matricxon_server_config(self._db)
        if config.cluster_role == "off":
            return
        name = registry.get(target).display_name
        raise ClusterSwitchUnconfirmedError(
            f"Matricxon cluster mode is on. Switching to {name} sends every chat to {name}; the cluster stays on and "
            "its nodes keep running, but the Cluster page is paused until you switch back to Matricxon."
        )
