"""Cluster page > Non-cluster hosts: Matricxon hosts pAIring still stores that the running cluster does not list.

Leftovers come from switching modes or a cluster reset (it keeps its nodes as plain hosts). With cluster mode off,
this is the engine's remote host list. Removing only edits pAIring's lists; an optional reset makes a reachable
host a fresh install again.
"""

import asyncio
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import MatricxonServerConfig
from app.schemas.cluster_outside import HostPlace, OutsideHost, OutsideHostList, OutsideRemoveResult, OutsideReset
from app.services import matricxon_http, matricxon_pool, server_pool_broadcast, settings_service
from app.services.cluster_errors import NodeNotAllowedError, NodeResetRefusedError
from app.services.cluster_hosts import ClusterHosts
from app.services.cluster_members import ClusterMembers
from app.services.cluster_nodes import ClusterNodes
from app.services.cluster_settings import ClusterSettings
from app.services.matricxon_pool import LOCAL_MATRICXON_HOST

logger = logging.getLogger("llama_chat")
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class OutsideHosts:
    def __init__(self, db: AsyncSession, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._db = db
        self._transport = transport

    async def read(self) -> OutsideHostList:
        config = await settings_service.get_matricxon_server_config(self._db)
        cluster = config.cluster_role != "off"
        members = ClusterMembers(self._db, self._transport)
        if cluster and not await members.load(config):
            return OutsideHostList(cluster=True, known=False, hosts=[])
        stored = self.stored(config)
        rows = await asyncio.gather(*(self._row(config, h, places) for h, places in stored.items()))
        hosts = [row for row, node_id in rows if not (cluster and members.is_member(config, row.host, node_id))]
        return OutsideHostList(cluster=cluster, known=True, hosts=hosts)

    @staticmethod
    def stored(config: MatricxonServerConfig) -> dict[str, list[HostPlace]]:
        """Every host pAIring keeps anywhere, with where it is kept."""
        found: dict[str, list[HostPlace]] = {}
        for host in ClusterHosts.nodes(config):
            places = found.setdefault(host, [])
            if config.mode == "local" and host == LOCAL_MATRICXON_HOST:
                places.append("local")
            if host in config.remote_hosts:
                places.append("remote")
            if host in config.cluster_hosts:
                places.append("cluster")
        for host in config.voter_hosts:
            found.setdefault(host, []).append("voter")
        for host in config.known_nodes:
            if host not in found:
                found[host] = ["remembered"]
        return found

    async def _row(
        self, config: MatricxonServerConfig, host: str, places: list[HostPlace]
    ) -> tuple[OutsideHost, str | None]:
        """The row, and the node id the host reports (None if it does not run cluster mode or is down)."""
        reachable, status = await asyncio.gather(self._answers(host), self._status(host))
        row = OutsideHost(
            host=host, places=places, reachable=reachable, consensus=status is not None, managed="local" in places
        )
        return row, (status or {}).get("node_id")

    async def _answers(self, host: str) -> bool:
        async with matricxon_http.client(timeout=_TIMEOUT, transport=self._transport) as client:
            try:
                return (await client.get(host + "/api/version")).status_code == 200
            except httpx.HTTPError:
                return False

    async def _status(self, host: str) -> dict | None:
        return await ClusterSettings(self._db, self._transport).status(host)

    async def remove(self, hosts: list[str], reset: bool) -> OutsideRemoveResult:
        """Takes the hosts out of every pAIring list at once; then resets the reachable ones if asked."""
        current = await self.read()
        if not current.known:
            raise NodeNotAllowedError("No voter answers, so pAIring can't tell which hosts are outside the cluster.")
        rows = {h.host: h for h in current.hosts}
        wanted = list(dict.fromkeys(hosts))
        unknown = [h for h in wanted if h not in rows]
        if unknown:
            raise NodeNotAllowedError("Not on the non-cluster list (refresh it): " + ", ".join(unknown))
        managed = [h for h in wanted if rows[h].managed]
        if managed:
            raise NodeNotAllowedError(
                f"{managed[0]} is the Matricxon pAIring runs: switch Matricxon to remote mode first."
            )
        config = await settings_service.get_matricxon_server_config(self._db)
        for host in wanted:
            self._forget(config, host)
        if config.mode == "remote" and not config.remote_hosts:
            raise NodeNotAllowedError("Keep at least one Matricxon host; nothing changed.")
        await settings_service.set_matricxon_server_config(self._db, config)
        matricxon_pool.refresh_from_config(config)
        await server_pool_broadcast.broadcast_refresh("/api/settings/matricxon/internal-refresh")
        logger.info("cluster: removed non-cluster host(s) %s", wanted)
        resets = [await self._reset(rows[h]) for h in wanted] if reset else []
        return OutsideRemoveResult(removed=wanted, resets=resets, state=await self.read())

    @staticmethod
    def _forget(config: MatricxonServerConfig, host: str) -> None:
        if host in ClusterHosts.nodes(config):
            ClusterHosts.without(config, host)
            return
        # Kept only as a voter or a remembered id: ClusterHosts.without would treat it as the managed node.
        config.voter_hosts = [h for h in config.voter_hosts if h != host]
        config.known_nodes.pop(host, None)

    async def _reset(self, row: OutsideHost) -> OutsideReset:
        if not row.reachable:
            return OutsideReset(host=row.host, ok=False, reason="not reachable")
        try:
            await ClusterNodes(self._db, self._transport).reset(row.host)
        except (NodeNotAllowedError, NodeResetRefusedError) as exc:
            return OutsideReset(host=row.host, ok=False, reason=str(exc))
        return OutsideReset(host=row.host, ok=True)
