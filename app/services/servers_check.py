"""Cluster > Servers: what several pAIring servers on one database need, checked across every online
server from its heartbeat details (server_facts.py). On SQLite, which only one machine can use, the list is
this server's own facts and the database check explains why."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.servers import FolderState, ServerCheck, ServerChecks, ServerFolders
from app.services import settings_service
from app.services.db_clock import shared_database
from app.services.server_facts import SHARED_FOLDERS, ServerFacts, server_facts
from app.services.server_registry import ServerRegistry, server_registry


class ServersCheck:
    def __init__(self, registry: ServerRegistry = server_registry, facts: ServerFacts = server_facts) -> None:
        self._registry = registry
        self._facts = facts

    async def run(self, db: AsyncSession) -> ServerChecks:
        if not shared_database(db):
            report = {self._registry.server_id: self._facts.report()}
            return ServerChecks(
                shared_database=False,
                checks=[self._database(False), self._secret(report)],
                folders=self._folders(report, {}),
            )
        rows, now = await self._registry.servers(db)
        online = [r for r in rows if self._registry.online(r, now) and r.details]
        reports = {r.server_id: r.details for r in online}
        markers = await self._facts.markers(db)
        primaries = sum(1 for r in online if r.is_primary)
        checks = [
            self._database(True),
            self._secret(reports),
            *[self._folder(name, reports, markers) for name in SHARED_FOLDERS],
            await self._matricxon_mode(db, primaries),
            self._versions({r.server_id: f"{r.version} {r.git_commit or ''}".strip() for r in online}),
        ]
        return ServerChecks(shared_database=True, checks=checks, folders=self._folders(reports, markers))

    @staticmethod
    def _database(shared: bool) -> ServerCheck:
        if shared:
            return ServerCheck(id="database", ok=True, title="Shared database (MySQL)")
        return ServerCheck(
            id="database",
            ok=False,
            title="Shared database",
            detail="This server uses SQLite, a local file only one machine can use.",
            fix="Switch to MySQL under System → Database, then point every server at it.",
        )

    @staticmethod
    def _secret(reports: dict[str, dict]) -> ServerCheck:
        unset = [sid for sid, r in reports.items() if not r.get("secret_set")]
        if unset:
            return ServerCheck(
                id="secret_key",
                ok=False,
                title="SECRET_KEY",
                detail=f"Not set on {', '.join(unset)}: a random key is used, and users are logged out on restart.",
                fix="Set the same SECRET_KEY on every server (below, for this server).",
            )
        if len({r.get("secret") for r in reports.values()}) > 1:
            return ServerCheck(
                id="secret_key",
                ok=False,
                title="Same SECRET_KEY on every server",
                detail="The servers use different keys: users are logged out when they reach another server.",
                fix="Copy one server's SECRET_KEY to all the others, then restart them.",
            )
        return ServerCheck(id="secret_key", ok=True, title="Same SECRET_KEY on every server")

    @staticmethod
    def _folder(name: str, reports: dict[str, dict], markers: dict) -> ServerCheck:
        wanted = {markers.get("ids", {}).get(name), markers.get("previous", {}).get(name)} - {None}
        apart = [sid for sid, r in reports.items() if r["folders"][name]["marker"] not in wanted]
        if not wanted:
            return ServerCheck(
                id=name, ok=None, title=f"{name} shared", detail="Checking: the leader is writing a marker."
            )
        if apart:
            return ServerCheck(
                id=name,
                ok=False,
                title=f"{name} shared",
                detail=f"Not the same folder as the leader's on {', '.join(apart)}.",
                fix="Mount one shared folder (e.g. NFS) on every server and point this setting at it.",
            )
        return ServerCheck(id=name, ok=True, title=f"{name} shared")

    @staticmethod
    async def _matricxon_mode(db: AsyncSession, primaries: int) -> ServerCheck:
        mode = (await settings_service.get_matricxon_server_config(db)).mode
        if mode == "remote" or primaries <= 1:
            return ServerCheck(id="matricxon_mode", ok=True, title="Matricxon in Remote mode (servers or a cluster)")
        return ServerCheck(
            id="matricxon_mode",
            ok=False,
            title="Matricxon in Remote mode (servers or a cluster)",
            detail="Local mode: every pAIring server treats Matricxon as the one on its own machine.",
            fix="Switch Matricxon to Remote under Inference engines (a cluster made here: switch it too).",
        )

    @staticmethod
    def _versions(versions: dict[str, str]) -> ServerCheck:
        if len(set(versions.values())) <= 1:
            return ServerCheck(id="versions", ok=True, title="Same pAIring version on every server")
        detail = ", ".join(f"{sid}: {v}" for sid, v in sorted(versions.items()))
        return ServerCheck(
            id="versions",
            ok=False,
            title="Same pAIring version on every server",
            detail=detail,
            fix="Use Update all servers.",
        )

    @staticmethod
    def _folders(reports: dict[str, dict], markers: dict) -> list[ServerFolders]:
        wanted = {
            name: {markers.get("ids", {}).get(name), markers.get("previous", {}).get(name)} - {None}
            for name in SHARED_FOLDERS
        }
        return [
            ServerFolders(
                server_id=sid,
                folders={
                    name: FolderState(
                        path=f["path"],
                        shared_fs=f["shared"],
                        same=(f["marker"] in wanted[name]) if wanted[name] else None,
                    )
                    for name, f in report["folders"].items()
                },
            )
            for sid, report in sorted(reports.items())
        ]


servers_check = ServersCheck()
