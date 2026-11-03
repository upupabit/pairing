"""services/upload_jobs.py: upload progress kept in the database, readable by any server."""

from datetime import timedelta

import pytest

from app.models import UploadJob
from app.models._base import utcnow
from app.services.upload_jobs import ProgressThrottle, upload_jobs

_EMPTY = {"document_count": 0, "chunk_count": 0, "used_mb": 0}


@pytest.mark.asyncio
async def test_progress_saved_by_the_job_is_what_a_poll_reads(db, user):
    await upload_jobs.create(db, "0-a", user.id, {"a.txt": {"status": "waiting"}}, done=False, result=None)

    await upload_jobs.save("0-a", {"a.txt": {"status": "processing", "chunk": 2}})
    summary = {"folder": "k", "mine": _EMPTY, "shared": _EMPTY, "limits": {"max_file_mb": 1, "max_user_space_mb": 1}}
    result = {"summary": summary, "uploaded": ["a.txt"], "errors": []}
    await upload_jobs.save("0-a", {"a.txt": {"status": "added"}}, done=True, result=result)

    job = await upload_jobs.get_for_user(db, "0-a", user)
    await db.refresh(job)  # the save ran in its own session
    status = upload_jobs.status(job)
    assert status.done is True
    assert status.files == {"a.txt": {"status": "added"}}
    assert status.result.uploaded == ["a.txt"]


@pytest.mark.asyncio
async def test_the_sweep_drops_finished_jobs_after_the_ttl_and_any_job_after_a_day(db, user):
    def job(job_id: str, done: bool, age: timedelta) -> UploadJob:
        return UploadJob(id=job_id, user_id=user.id, done=done, files={}, created_at=utcnow() - age)

    late = upload_jobs.TTL + timedelta(minutes=1)
    db.add_all(
        [
            job("done-old", True, late),
            job("running-recent", False, late),
            job("running-stale", False, timedelta(days=2)),
            job("done-new", True, timedelta(minutes=1)),
        ]
    )
    await db.commit()

    assert await upload_jobs.prune(db) == 2

    kept = {j for j in ("done-old", "running-recent", "running-stale", "done-new") if await db.get(UploadJob, j)}
    assert kept == {"running-recent", "done-new"}


@pytest.mark.asyncio
async def test_a_restart_ends_only_this_servers_unfinished_uploads_with_a_reason(db, user):
    await upload_jobs.create(db, "mine", user.id, {}, done=False, result=None)
    db.add(UploadJob(id="theirs", user_id=user.id, done=False, files={}, owner_server="other:8000"))
    await db.commit()

    assert await upload_jobs.interrupt(db) == 1

    db.expire_all()
    mine, theirs = await db.get(UploadJob, "mine"), await db.get(UploadJob, "theirs")
    assert mine.done and "Interrupted" in upload_jobs.status(mine).error
    assert not theirs.done


def test_progress_throttle_allows_one_write_per_interval():
    throttle = ProgressThrottle(60.0)
    assert throttle.due() is True
    assert throttle.due() is False
