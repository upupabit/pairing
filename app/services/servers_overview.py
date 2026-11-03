"""Admin settings > Update > Servers: what the server list shows. On a shared database (MySQL), every server's
heartbeat row; on SQLite, which only one machine can use, this machine's own processes, without database
writes (server_heartbeat.py skips them there)."""

import socket

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import APP_VERSION, INSTANCE_INDEX, SERVER_ID
from app.schemas.servers import RolloutOut, ServerOut, ServersOverview
from app.services import instance_process
from app.services.db_clock import shared_database
from app.services.rolling_update import RollingUpdate, RolloutError, rolling_update
from app.services.server_registry import ServerRegistry, local_commit, server_registry


class ServersOverviewService:
    def __init__(self, registry: ServerRegistry = server_registry, rollout: RollingUpdate = rolling_update) -> None:
        self._registry = registry
        self._rollout = rollout

    async def overview(self, db: AsyncSession) -> ServersOverview:
        if not shared_database(db):
            return ServersOverview(servers=self._local_servers(), shared_database=False)
        rows, now = await self._registry.servers(db)
        holder = (await db.execute(text("SELECT holder FROM leader_leases WHERE name = 'leader'"))).scalar()
        rollout = await self._rollout.get(db)
        servers = [
            ServerOut(
                server_id=row.server_id,
                machine=(row.details or {}).get("machine") or row.server_id.rsplit(":", 1)[0],
                version=row.version,
                git_commit=row.git_commit,
                is_primary=row.is_primary,
                online=self._registry.online(row, now),
                leader=row.server_id == holder,
                seconds_since_seen=max(0, now - row.last_seen),
                this_server=row.server_id == self._registry.server_id,
                update_state=row.update_state if rollout and row.update_round == rollout["id"] else None,
                update_progress=(row.details or {}).get("update_progress") if row.update_state == "updating" else None,
            )
            for row in rows
        ]
        return ServersOverview(
            servers=servers, rollout=RolloutOut(**rollout) if rollout else None, server_time=int(now)
        )

    async def start_update_all(self, db: AsyncSession) -> ServersOverview:
        if not shared_database(db):
            raise RolloutError("This server uses SQLite, so it is the only one: update it on the Update tab.")
        await self._rollout.start(db)
        return await self.overview(db)

    async def cancel_update_all(self, db: AsyncSession) -> ServersOverview:
        await self._rollout.cancel(db)
        return await self.overview(db)

    @staticmethod
    def _local_servers() -> list[ServerOut]:
        """The primary and its running local instances; all online (the primary is the leader)."""
        alive = [i for i, info in instance_process.read_tracking().items() if instance_process.is_alive(info["pid"])]
        commit = local_commit()
        servers = []
        for index in [0, *sorted(alive)]:
            server_id = (
                SERVER_ID
                if index == INSTANCE_INDEX
                else f"{socket.gethostname()}:{instance_process.port_for_index(index)}"
            )
            servers.append(
                ServerOut(
                    server_id=server_id,
                    machine=socket.gethostname(),
                    version=APP_VERSION,
                    git_commit=commit,
                    is_primary=index == 0,
                    online=True,
                    leader=index == 0,
                    seconds_since_seen=0,
                    this_server=index == INSTANCE_INDEX,
                )
            )
        return servers


servers_overview = ServersOverviewService()
