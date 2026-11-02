"""Which of pAIring's Matricxon hosts the running cluster lists as members.

Asks a voter for the cluster's node list. A host is a member when it was added on the Cluster page, when its
remembered or reported node id is listed, or when the same machine and port is listed.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import MatricxonServerConfig
from app.services.cluster_nodes import ClusterNodes
from app.services.cluster_settings import ClusterSettings


class ClusterMembers:
    def __init__(self, db: AsyncSession, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._db = db
        self._transport = transport
        self._nodes: dict[str, str] = {}
        self._keys: set[tuple[str, str, int | None]] = set()

    async def load(self, config: MatricxonServerConfig) -> bool:
        """Reads the cluster's node list; False when there is no cluster to ask (off, no voter, older Matricxon)."""
        if config.cluster_role == "off":
            return False
        entry = await ClusterSettings(self._db, self._transport).entry_voter()
        self._nodes = (entry[1].get("nodes") or {}) if entry else {}
        self._keys = {ClusterNodes.pool_key(a.rstrip("/")) for a in self._nodes.values()}
        return bool(self._nodes)

    def is_member(self, config: MatricxonServerConfig, host: str, node_id: str | None = None) -> bool:
        """Needs `load()` first. `node_id`: what the host reports now, if it answers."""
        remembered = (config.known_nodes.get(host) or {}).get("node_id")
        return (
            host in config.cluster_hosts
            or remembered in self._nodes
            or (node_id is not None and node_id in self._nodes)
            or ClusterNodes.pool_key(host) in self._keys
        )

    async def members(self, config: MatricxonServerConfig, hosts: list[str]) -> list[str]:
        """The `hosts` the cluster lists; all of them when there is no cluster to ask."""
        if not hosts or not await self.load(config):
            return hosts
        return [h for h in hosts if self.is_member(config, h)]
