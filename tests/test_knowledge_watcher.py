"""knowledge/ changes picked up without a restart (services/knowledge_watcher.py)."""

import pytest

from app.services.knowledge_watcher import KnowledgeWatcher


def _watcher(tmp_path, uploads=False):
    calls = []

    async def sync():
        calls.append(1)
        return {"added": 1, "updated": 0, "removed": 0, "errors": []}

    async def uploads_running():
        return uploads

    return KnowledgeWatcher(tmp_path, sync, uploads_running), calls


@pytest.mark.asyncio
async def test_a_new_file_is_synced_once_it_settles(tmp_path):
    watcher, calls = _watcher(tmp_path)
    watcher.mark_synced()
    (tmp_path / "global").mkdir()
    (tmp_path / "global" / "a.txt").write_text("hello")

    assert not await watcher.check_once()  # seen, waiting one more check
    assert await watcher.check_once()
    assert not await watcher.check_once()  # nothing new
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_edits_removals_and_unsupported_files(tmp_path):
    watcher, calls = _watcher(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("one")
    watcher.mark_synced()
    (tmp_path / "picture.exe").write_bytes(b"x")  # not a knowledge file
    assert not await watcher.check_once() and not await watcher.check_once()

    doc.write_text("one, two")
    await watcher.check_once()
    assert await watcher.check_once()
    doc.unlink()
    await watcher.check_once()
    assert await watcher.check_once()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_waits_while_a_browser_upload_runs(tmp_path):
    watcher, calls = _watcher(tmp_path, uploads=True)
    watcher.mark_synced()
    (tmp_path / "a.txt").write_text("x")

    await watcher.check_once()
    assert not await watcher.check_once()
    assert calls == []


@pytest.mark.asyncio
async def test_a_stale_unfinished_upload_does_not_block(db, monkeypatch):
    from datetime import timedelta

    from app.models import UploadJob
    from app.models._base import utcnow
    from app.services import knowledge_watcher as module

    monkeypatch.setattr(module, "AsyncSessionLocal", lambda: _Same(db))
    db.add(UploadJob(id="old", user_id="u", files={}, done=False, created_at=utcnow() - timedelta(hours=3)))
    await db.commit()
    assert not await KnowledgeWatcher._any_upload_running()
    db.add(UploadJob(id="new", user_id="u", files={}, done=False))
    await db.commit()
    assert await KnowledgeWatcher._any_upload_running()


class _Same:
    """The test's session as an `async with` block, left open."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_exc):
        return False
