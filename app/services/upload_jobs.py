"""Knowledge-base upload jobs in the database, so a progress poll that reaches another server (a load
balancer in front of several machines) still finds its job. The job itself runs on the server that
started it (document_upload._run_upload_job); progress writes are throttled to PROGRESS_SECONDS.
"""

import time
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import and_, delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SERVER_ID
from app.database import AsyncSessionLocal
from app.models import UploadJob, User
from app.models._base import utcnow
from app.schemas import UploadJobStatus


class UploadJobStore:
    TTL = timedelta(minutes=30)
    PROGRESS_SECONDS = 3.0

    def __init__(self, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal) -> None:
        self._session_factory = session_factory

    async def create(
        self, db: AsyncSession, job_id: str, user_id: str, files: dict, done: bool, result: dict | None
    ) -> UploadJob:
        job = UploadJob(id=job_id, user_id=user_id, done=done, files=files, result=result, owner_server=SERVER_ID)
        db.add(job)
        await db.commit()
        return job

    async def get_for_user(self, db: AsyncSession, job_id: str, user: User) -> UploadJob | None:
        """None unless `user` started it or is an admin: the id is visible in the browser, and must not show
        others' filenames and errors."""
        job = await db.get(UploadJob, job_id)
        if job is None or (job.user_id != user.id and user.role != "admin"):
            return None
        return job

    @staticmethod
    def status(job: UploadJob) -> UploadJobStatus:
        return UploadJobStatus(job_id=job.id, done=job.done, files=job.files, result=job.result, error=job.error)

    async def save(self, job_id: str, files: dict, done: bool = False, result: dict | None = None) -> None:
        """From the background job, in its own session (the request's is closed by then)."""
        async with self._session_factory() as db:
            values = {"files": dict(files), "done": done}
            if result is not None:
                values["result"] = result
            await db.execute(update(UploadJob).where(UploadJob.id == job_id).values(**values))
            await db.commit()

    async def interrupt(self, db: AsyncSession, server_id: str = SERVER_ID, unowned: bool = False) -> int:
        """Ends `server_id`'s unfinished jobs (it restarted or went offline: the job's task is gone), so their
        progress bars stop with a reason. `unowned` also ends jobs from before owners were recorded."""
        owner = UploadJob.owner_server == server_id
        result = await db.execute(
            update(UploadJob)
            .where(UploadJob.done.is_(False))
            .where(or_(owner, UploadJob.owner_server.is_(None)) if unowned else owner)
            .values(done=True, error="Interrupted by a server restart. Please upload the files again.")
        )
        await db.commit()
        return result.rowcount

    async def prune(self, db: AsyncSession) -> int:
        """From the retention sweep: finished jobs after TTL, any job after a day."""
        now = utcnow()
        old = or_(
            and_(UploadJob.done.is_(True), UploadJob.created_at < now - self.TTL),
            UploadJob.created_at < now - timedelta(days=1),
        )
        result = await db.execute(delete(UploadJob).where(old))
        await db.commit()
        return result.rowcount


class ProgressThrottle:
    """True at most once per `seconds`, so chunk progress doesn't write a row per chunk."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._last = 0.0

    def due(self) -> bool:
        now = time.monotonic()
        if now - self._last < self._seconds:
            return False
        self._last = now
        return True


upload_jobs = UploadJobStore()
