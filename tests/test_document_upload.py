"""Tests for services/document_upload.py's job-id shape (instance_proxy routes a poll by its prefix) and the
upload job's ownership check, now that jobs are database rows (upload_jobs.py).
"""

import pytest

from app.services import document_upload
from app.services.upload_jobs import upload_jobs


@pytest.mark.asyncio
async def test_start_upload_job_id_is_prefixed_with_this_instance_index(db, user, tmp_path, monkeypatch):
    monkeypatch.setattr(document_upload, "INSTANCE_INDEX", 3)

    status = await document_upload.start_upload_job(
        db,
        background_tasks=None,
        target_dir=tmp_path,
        owner_id=user.id,
        accepted=[],
        rejects=[],
        user=user,
    )

    assert status.job_id.startswith("3-")
    assert await upload_jobs.get_for_user(db, status.job_id, user) is not None


@pytest.mark.asyncio
async def test_a_job_is_visible_only_to_its_user_and_admins(db, user, admin_user, channel_manager_user, tmp_path):
    """Security regression: a job id is visible in the browser, so it must not let others read upload filenames
    and errors."""
    status = await document_upload.start_upload_job(
        db,
        background_tasks=None,
        target_dir=tmp_path,
        owner_id=user.id,
        accepted=[],
        rejects=[],
        user=user,
    )

    assert await upload_jobs.get_for_user(db, status.job_id, user) is not None
    assert await upload_jobs.get_for_user(db, status.job_id, admin_user) is not None
    assert await upload_jobs.get_for_user(db, status.job_id, channel_manager_user) is None
    assert await upload_jobs.get_for_user(db, "does-not-exist", user) is None


@pytest.mark.asyncio
async def test_an_all_rejected_upload_is_done_at_once_with_its_errors(db, user, tmp_path):
    status = await document_upload.start_upload_job(
        db,
        background_tasks=None,
        target_dir=tmp_path,
        owner_id=user.id,
        accepted=[],
        rejects=[("bad.exe", "unsupported file type.")],
        user=user,
    )

    assert status.done is True
    assert status.files["bad.exe"]["status"] == "error"
    assert status.result.errors == ["bad.exe: unsupported file type."]
