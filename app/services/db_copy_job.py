"""Admin settings > System > Database > "Copy my data": the copy and switch as a background job, so Settings can
show its progress (GET /api/settings/database/copy) instead of waiting on one long request. One at a time; it
lives on the primary, which every /api/settings/database request reaches (instance_proxy_http.EXEMPT_PREFIXES).
"""

import asyncio

from app.schemas import DbConfigUpdate
from app.schemas.db_config import DbCopyStatus
from app.services import db_config_service
from app.services.db_data_copy import CopyProgress


class CopyJobBusyError(RuntimeError):
    """A copy is already running."""


class DatabaseCopyJob:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._progress: CopyProgress | None = None
        self._result = None

    def start(self, update: DbConfigUpdate) -> DbCopyStatus:
        if self._task and not self._task.done():
            raise CopyJobBusyError("A copy is already running.")
        self._progress, self._result = CopyProgress(), None
        self._task = asyncio.create_task(self._run(update.model_copy(update={"copy_data": True})))
        return self.status()

    async def _run(self, update: DbConfigUpdate) -> None:
        self._result = await db_config_service.save_and_apply(update, self._progress)

    def status(self) -> DbCopyStatus:
        if self._progress is None:
            return DbCopyStatus(running=False)
        p, result = self._progress, self._result
        return DbCopyStatus(
            running=result is None,
            stage=p.stage,
            table=p.table,
            done=p.done,
            total=p.total,
            ok=result.ok if result else None,
            message=result.message if result else None,
        )


database_copy_job = DatabaseCopyJob()
