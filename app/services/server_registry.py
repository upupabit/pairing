"""The list of pAIring servers sharing a database: each process writes a heartbeat row every
HEARTBEAT_SECONDS (servers table). The leader also ends the unfinished replies, image and upload jobs of servers
gone offline, and forgets servers offline for FORGET_SECONDS.
"""

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import APP_VERSION, BASE_DIR, IS_PRIMARY, SERVER_ID
from app.database import AsyncSessionLocal
from app.models import Server
from app.services.conversation_service import mark_interrupted_messages_as_errored
from app.services.db_clock import db_epoch
from app.services.image_generation_service import mark_interrupted_jobs_as_errored
from app.services.upload_jobs import upload_jobs

logger = logging.getLogger("llama_chat")


def local_commit(base_dir: Path = BASE_DIR) -> str | None:
    """This checkout's short git commit, or None (a download install)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


class ServerRegistry:
    HEARTBEAT_SECONDS = 10
    OFFLINE_SECONDS = 60
    FORGET_SECONDS = 7 * 24 * 3600

    def __init__(
        self,
        server_id: str = SERVER_ID,
        is_primary: bool = IS_PRIMARY,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self.server_id = server_id
        self._is_primary = is_primary
        self._session_factory = session_factory
        self._commit = local_commit()

    async def heartbeat(self, db: AsyncSession, details: dict | None = None) -> None:
        """`details`: what server_facts.py reports, compared by servers_check.py."""
        values = {
            "version": APP_VERSION,
            "git_commit": self._commit,
            "is_primary": self._is_primary,
            "last_seen": await db_epoch(db),
            "details": details,
        }
        found = await db.execute(update(Server).where(Server.server_id == self.server_id).values(**values))
        if found.rowcount == 0:
            try:
                async with db.begin_nested():
                    db.add(Server(server_id=self.server_id, **values))
            except IntegrityError:
                pass  # created by a parallel heartbeat
        await db.commit()

    async def servers(self, db: AsyncSession) -> tuple[list[Server], int]:
        """Every known server, and the database's now (to tell online from offline)."""
        rows = (await db.execute(select(Server).order_by(Server.server_id))).scalars().all()
        return list(rows), await db_epoch(db)

    def online(self, server: Server, now: int) -> bool:
        return now - server.last_seen < self.OFFLINE_SECONDS

    async def own_row(self, db: AsyncSession) -> Server | None:
        return await db.get(Server, self.server_id)

    async def set_update_state(self, db: AsyncSession, update_round: str | None, state: str | None) -> None:
        await db.execute(
            update(Server)
            .where(Server.server_id == self.server_id)
            .values(update_round=update_round, update_state=state)
        )
        await db.commit()

    async def set_update_progress(self, db: AsyncSession, progress: dict | None) -> None:
        """Shares this server's update step in its details, between heartbeats (which keep it too)."""
        row = await self.own_row(db)
        if row is None:
            return
        details = {k: v for k, v in (row.details or {}).items() if k != "update_progress"}
        if progress:
            details["update_progress"] = progress
        row.details = details
        await db.commit()

    async def sweep_offline(self, db: AsyncSession) -> None:
        """Leader only: replies of an offline server can't finish, so they stop showing "typing"."""
        rows, now = await self.servers(db)
        for server in rows:
            if self.online(server, now):
                continue
            replies = await mark_interrupted_messages_as_errored(db, server_id=server.server_id, unowned=False)
            jobs = await mark_interrupted_jobs_as_errored(db, server_id=server.server_id, unowned=False)
            await upload_jobs.interrupt(db, server_id=server.server_id)
            if replies or jobs:
                logger.info("Cleared %d repl(ies) and %d image job(s) of offline %s.", replies, jobs, server.server_id)
        await db.execute(delete(Server).where(Server.last_seen < now - self.FORGET_SECONDS))
        await db.commit()

    async def forget(self, db: AsyncSession, server_id: str) -> bool:
        """Removes an offline server from the list; False when it is online (it would come back)."""
        server = await db.get(Server, server_id)
        if server is None:
            return True
        if self.online(server, await db_epoch(db)):
            return False
        await db.delete(server)
        await db.commit()
        return True


server_registry = ServerRegistry()
