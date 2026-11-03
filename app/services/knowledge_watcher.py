"""Picks up files added, edited or removed in knowledge/ without a restart.

A cheap check every KNOWLEDGE_WATCH_SECONDS: each file's path, size and change time. Polling rather than
inotify, which misses changes on NFS shares (the cluster's shared storage). A change is synced once it has
stayed the same for one more check (a large copy may still be writing), and never while a browser upload
is running (it syncs its own files). Leader only (leader_lease.py): the folder and tables are shared.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.config import KNOWLEDGE_DIR, KNOWLEDGE_WATCH_SECONDS
from app.database import AsyncSessionLocal
from app.models import UploadJob
from app.models._base import utcnow
from app.services.document_extract import SUPPORTED_EXTENSIONS
from app.services.leader_lease import leader_lease

logger = logging.getLogger("llama_chat")

Fingerprint = frozenset[tuple[str, int, int]]


class KnowledgeWatcher:
    def __init__(
        self,
        root: Path = KNOWLEDGE_DIR,
        sync: Callable[[], Awaitable[dict]] | None = None,
        uploads_running: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._root = root
        self._sync = sync or self._sync_all
        self._uploads_running = uploads_running or self._any_upload_running
        self._synced: Fingerprint | None = None  # what the last sync saw
        self._pending: Fingerprint | None = None  # a change waiting to settle
        self._task: asyncio.Task | None = None

    def fingerprint(self) -> Fingerprint:
        files = set()
        for path in self._root.rglob("*"):
            try:
                if path.suffix.lower() in SUPPORTED_EXTENSIONS and path.is_file():
                    info = path.stat()
                    files.add((str(path.relative_to(self._root)), info.st_size, info.st_mtime_ns))
            except OSError:
                continue  # removed while scanning
        return frozenset(files)

    def mark_synced(self) -> None:
        """Startup's own sync just ran: start from what it saw."""
        self._synced = self.fingerprint()

    async def check_once(self) -> bool:
        """True when it synced."""
        now = self.fingerprint()
        if now == self._synced:
            self._pending = None
            return False
        if now != self._pending:
            self._pending = now  # changed: wait one more check for it to settle
            return False
        if await self._uploads_running():
            return False
        stats = await self._sync()
        self._synced, self._pending = now, None
        logger.info(
            "Knowledge folder changed: %d added, %d updated, %d removed.",
            stats["added"],
            stats["updated"],
            stats["removed"],
        )
        for error in stats["errors"]:
            logger.warning("Knowledge base: %s", error)
        return True

    def start(self) -> None:
        if KNOWLEDGE_WATCH_SECONDS > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(KNOWLEDGE_WATCH_SECONDS)
            try:
                if leader_lease.is_leader:
                    await self.check_once()
            except Exception:
                logger.exception("Knowledge folder check failed.")  # keep watching

    @staticmethod
    async def _sync_all() -> dict:
        from app.services.document_sync import sync_all_on_startup  # avoids an import cycle at startup

        async with AsyncSessionLocal() as db:
            return await sync_all_on_startup(db)

    @staticmethod
    async def _any_upload_running() -> bool:
        """Only recent ones: a job left unfinished by a crash must not stop the watcher for good."""
        recent = utcnow() - timedelta(hours=1)
        query = select(func.count()).where(UploadJob.done.is_(False), UploadJob.created_at > recent)
        async with AsyncSessionLocal() as db:
            return bool((await db.execute(query)).scalar())


knowledge_watcher = KnowledgeWatcher()
