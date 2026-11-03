"""Cluster > Matricxon > "Update all nodes": every Matricxon node updates itself from GitHub, one at a time
(matricxon_node_update.py), the consensus leader last, stopping at the first error. In a cluster the next node
starts only once the last one is back with a quorum, so the cluster keeps serving.

Run by the pAIring server that started it, as a task, so it works on SQLite too. The rollout is one app_settings
row (KEY), the same shape as the pAIring servers' rollout (rolling_update.py), so Settings draws both alike.
A cancel from any server marks the row; the task stops before the next node. If the server running it stops,
the row goes stale and reads as stopped.
"""

import asyncio
import copy
import time
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SERVER_ID
from app.database import AsyncSessionLocal
from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas.matricxon_rollout import MatricxonRolloutOverview, NodeVersion, RolloutNode
from app.schemas.servers import RolloutOut
from app.services import matricxon_http, settings_service
from app.services.cluster_hosts import ClusterHosts
from app.services.matricxon_node_update import NodeUpdate
from app.services.rolling_update import RolloutError
from app.services.update_source import UpdateSourceService

_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


class MatricxonRollout:
    KEY = "matricxon_rolling_update"
    SAVE_SECONDS = 3.0
    STALE_SECONDS = 90

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._transport = transport
        self._task: asyncio.Task | None = None
        self._saved_at = 0.0

    async def get(self, db: AsyncSession) -> dict | None:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, self.KEY))
        rollout = copy.deepcopy(row.value) if row else None
        if rollout and rollout["status"] == "running" and time.time() - rollout["touched_at"] > self.STALE_SECONDS:
            message = f"The pAIring server running it ({rollout['owner']}) stopped."
            rollout.update(status="stopped", message=message, finished_at=rollout["touched_at"])
        return rollout

    async def overview(self, db: AsyncSession) -> MatricxonRolloutOverview:
        """The rollout with each node's stage, as ServersOverview has it for pAIring servers."""
        rollout = await self.get(db)
        if not rollout:
            return MatricxonRolloutOverview(server_time=int(time.time()))
        state = rollout.get("node_state") or {}
        nodes = [
            RolloutNode(
                server_id=host,
                leader=host == rollout.get("leader"),
                update_state=state.get("state") if host == rollout["current"] else None,
                update_progress=state.get("progress") if host == rollout["current"] else None,
            )
            for host in rollout["order"]
        ]
        return MatricxonRolloutOverview(rollout=RolloutOut(**rollout), servers=nodes, server_time=int(time.time()))

    async def node_versions(self, db: AsyncSession) -> list[NodeVersion]:
        """Every node's version and commit now, for the list above the button."""
        config = await settings_service.get_matricxon_server_config(db)
        nodes = ClusterHosts.nodes(config)

        async def one(client: httpx.AsyncClient, host: str) -> NodeVersion:
            try:
                resp = await client.get(f"{host.rstrip('/')}/api/version")
                body = resp.json() if resp.status_code == 200 else {}
            except (httpx.HTTPError, ValueError) as exc:
                return NodeVersion(host=host, reachable=False, error=str(exc) or type(exc).__name__)
            return NodeVersion(host=host, reachable=bool(body), version=body.get("version"), commit=body.get("commit"))

        async with matricxon_http.client(timeout=httpx.Timeout(4.0), transport=self._transport) as client:
            versions = list(await asyncio.gather(*(one(client, h) for h in nodes)))
            leader = await self._leader(client, nodes) if config.cluster_role != "off" else None
        for version in versions:
            version.leader = version.host == leader
        return versions

    async def start(self, db: AsyncSession) -> dict:
        current = await self.get(db)
        if current and current["status"] == "running":
            raise RolloutError("An update of all nodes is already running.")
        config = await settings_service.get_matricxon_server_config(db)
        nodes = ClusterHosts.nodes(config)
        cluster = config.cluster_role != "off"
        async with self._client() as client:
            leader = await self._leader(client, nodes) if cluster else None
        order = sorted(nodes, key=lambda host: host == leader)  # the leader last: one leader change
        now = int(time.time())
        rollout = {
            "id": uuid.uuid4().hex,
            "status": "running",
            "order": order,
            "queue": list(order),
            "current": None,
            "results": {},
            "durations": {},
            "started_at": now,
            "finished_at": None,
            "current_since": now,
            "message": None,
            "cluster": cluster,
            "leader": leader,
            "owner": SERVER_ID,
            "touched_at": now,
            "node_state": None,
        }
        await self._write(db, rollout)
        self._task = asyncio.create_task(self._run(rollout))
        return await self.get(db)

    async def cancel(self, db: AsyncSession) -> dict | None:
        """Stops before the next node; one already updating finishes."""
        rollout = await self.get(db)
        if rollout and rollout["status"] == "running":
            rollout.update(status="cancelled", queue=[], message="Cancelled by an admin.", finished_at=int(time.time()))
            await self._write(db, rollout)
        return rollout

    async def _run(self, rollout: dict) -> None:
        async with self._client() as client:
            while rollout["status"] == "running" and rollout["queue"]:
                host = rollout["queue"].pop(0)
                rollout.update(current=host, current_since=int(time.time()), node_state={"state": "updating"})
                await self._save(rollout, force=True)

                async def report(stage: str | None, progress: dict | None) -> None:
                    if stage:
                        rollout["node_state"] = {"state": stage, "progress": progress}
                    await self._save(rollout, force=stage is not None and stage != "updating")

                try:
                    async with self._session_factory() as db:
                        remote = await UpdateSourceService(db).remote("matricxon")
                    result = await NodeUpdate(client, host, rollout["cluster"], report, remote).run()
                except Exception as exc:  # noqa: BLE001 - shown to the admin, never left "running"
                    result = f"error: {exc}"
                rollout["results"][host] = result
                rollout["durations"][host] = int(time.time()) - rollout["current_since"]
                rollout["node_state"] = None
                if result.startswith("error"):
                    rollout.update(status="stopped", message=f"{host}: {result}")
                else:
                    rollout["current"] = None
                await self._save(rollout, force=True)
        if rollout["status"] == "running":
            rollout.update(status="finished", finished_at=int(time.time()))
        elif rollout["status"] == "stopped":
            rollout["finished_at"] = int(time.time())
        await self._save(rollout, force=True)

    async def _save(self, rollout: dict, force: bool = False) -> None:
        """Throttled to SAVE_SECONDS unless `force`. Adopts a cancel written by any server meanwhile."""
        if not force and time.monotonic() - self._saved_at < self.SAVE_SECONDS:
            return
        self._saved_at = time.monotonic()
        async with self._session_factory() as db:
            row = await db.get(AppSetting, (SYSTEM_OWNER_ID, self.KEY))
            stored = row.value if row else {}
            if stored.get("id") == rollout["id"] and stored.get("status") == "cancelled":
                rollout.update(status="cancelled", queue=[], message=stored.get("message"))
                rollout["finished_at"] = stored.get("finished_at")
            rollout["touched_at"] = int(time.time())
            await self._write(db, rollout)

    async def _leader(self, client: httpx.AsyncClient, nodes: list[str]) -> str | None:
        """The host that is the consensus leader now, if any answers."""

        async def status(host: str) -> dict:
            try:
                resp = await client.get(f"{host.rstrip('/')}/api/consensus/status")
                return resp.json() if resp.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                return {}

        statuses = await asyncio.gather(*(status(h) for h in nodes))
        leader = next((s.get("leader") for s in statuses if s.get("leader")), None)
        return next((h for h, s in zip(nodes, statuses, strict=True) if leader and s.get("node_id") == leader), None)

    def _client(self) -> httpx.AsyncClient:
        return matricxon_http.client(timeout=_TIMEOUT, transport=self._transport)

    async def _write(self, db: AsyncSession, value: dict) -> None:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, self.KEY))
        if row is None:
            db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=self.KEY, value=copy.deepcopy(value)))
        else:
            row.value = copy.deepcopy(value)
        await db.commit()


matricxon_rollout = MatricxonRollout()
