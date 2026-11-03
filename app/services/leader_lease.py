"""One leader among the pAIring servers sharing a database, for the jobs that must run once overall
(engine status polling, retention sweep, cluster member sync, knowledge folder sync).

Each primary process runs one atomic UPDATE every RENEW_SECONDS: it takes the lease when it is free or
expired, or renews its own. Times come from the database clock, so machine clocks don't matter. A
leader that stops renewing loses the lease after TTL_SECONDS and another server takes over. On SQLite
(one machine) the primary is the leader without writing anything.
"""

import asyncio
import logging
import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SERVER_ID
from app.database import AsyncSessionLocal
from app.models import LeaderLease as LeaseRow
from app.services.db_clock import db_epoch_sql, shared_database

logger = logging.getLogger("llama_chat")


class LeaderLease:
    TTL_SECONDS = 30
    RENEW_SECONDS = 10

    def __init__(
        self,
        name: str = "leader",
        server_id: str = SERVER_ID,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
        shared: Callable[[AsyncSession], bool] = shared_database,
    ) -> None:
        self._name = name
        self._shared = shared
        self._server_id = server_id
        self._session_factory = session_factory
        self._leader = False
        self._renewed_at = 0.0
        self._task: asyncio.Task | None = None

    @property
    def is_leader(self) -> bool:
        """False once a renewal is overdue, even before another server takes over."""
        return self._leader and time.monotonic() - self._renewed_at < self.TTL_SECONDS

    async def acquire_once(self) -> bool:
        async with self._session_factory() as db:
            if not self._shared(db):
                return self._won(True)  # SQLite: the only server, no lease to write
            now = db_epoch_sql(db)
            sql = text(
                f"UPDATE leader_leases SET holder = :me, expires_at = {now} + :ttl "
                f"WHERE name = :name AND (holder = :me OR expires_at < {now})"
            )
            params = {"me": self._server_id, "ttl": self.TTL_SECONDS, "name": self._name}
            won = (await db.execute(sql, params)).rowcount == 1
            if not won and await db.get(LeaseRow, self._name) is None:
                await self._create_row(db)
                won = (await db.execute(sql, params)).rowcount == 1
            await db.commit()
        return self._won(won)

    def _won(self, won: bool) -> bool:
        if won != self._leader:
            logger.info("Leader lease %s by %s.", "taken" if won else "lost", self._server_id)
        self._leader = won
        if won:
            self._renewed_at = time.monotonic()
        return won

    async def release(self) -> None:
        """Frees the lease at shutdown, so another server takes over at once."""
        async with self._session_factory() as db:
            if not self._shared(db):
                self._leader = False
                return
            await db.execute(
                text("UPDATE leader_leases SET holder = NULL, expires_at = 0 WHERE name = :name AND holder = :me"),
                {"name": self._name, "me": self._server_id},
            )
            await db.commit()
        self._leader = False

    async def start(self) -> None:
        """One attempt now, so startup knows the answer, then renewals in the background."""
        await self._attempt()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._leader:
            try:
                await self.release()
            except Exception:  # noqa: BLE001 - shutdown must go on; the lease expires anyway
                logger.exception("Could not release the leader lease.")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.RENEW_SECONDS)
            await self._attempt()

    async def _attempt(self) -> None:
        try:
            await self.acquire_once()
        except Exception:  # noqa: BLE001 - a database hiccup must not end the loop
            logger.exception("Leader lease renewal failed.")

    async def _create_row(self, db: AsyncSession) -> None:
        """Only when the migration's seed row is missing (e.g. a schema built from the models)."""
        try:
            async with db.begin_nested():
                db.add(LeaseRow(name=self._name, holder=None, expires_at=0))
        except IntegrityError:
            pass  # another server created it first


leader_lease = LeaderLease()
