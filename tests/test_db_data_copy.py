"""services/db_data_copy.py: copying every table into a fresh database when switching."""

import pytest
from sqlalchemy import create_engine, func, select

from app import models
from app.database import Base
from app.services.db_data_copy import CopyProgress, DatabaseCopier, DataCopyError


def _database(path, *rows) -> str:
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table, values in rows:
            conn.execute(table.insert(), values)
    engine.dispose()
    return url


def _user(user_id: str, name: str) -> dict:
    return {"id": user_id, "username": name, "password_hash": "x", "role": "admin"}


def _count(url: str, table) -> int:
    engine = create_engine(url)
    with engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(table)).scalar()
    engine.dispose()
    return n


def test_everything_is_copied_and_the_starter_admin_replaced(tmp_path):
    users, conversations, messages, settings = (
        models.User.__table__,
        models.Conversation.__table__,
        models.Message.__table__,
        models.AppSetting.__table__,
    )
    source = _database(
        tmp_path / "old.db",
        (users, [_user("u1", "admin"), _user("u2", "dana")]),
        (conversations, [{"id": "c1", "owner_id": "u2", "title": "t", "model": "m"}]),
        (
            messages,
            [
                {"id": "m1", "conversation_id": "c1", "role": "user", "content": "hi", "status": "complete"},
                {
                    "id": "m2",
                    "conversation_id": "c1",
                    "role": "assistant",
                    "content": "hello",
                    "status": "complete",
                    "reply_to_message_id": "m1",
                },
            ],
        ),
        (settings, [{"owner_id": "system", "key": "k", "value": {"nested": [1, 2]}}]),
    )
    target = _database(tmp_path / "new.db", (users, [_user("fresh", "admin")]))

    copied = DatabaseCopier(source, target).copy()

    assert copied == 6
    assert _count(target, users) == 2 and _count(target, messages) == 2
    engine = create_engine(target)
    with engine.connect() as conn:
        assert conn.execute(select(users.c.id).where(users.c.username == "admin")).scalar() == "u1"
        assert conn.execute(select(settings.c.value)).scalar() == {"nested": [1, 2]}
    engine.dispose()


def test_a_target_with_its_own_data_is_refused(tmp_path):
    users, conversations = models.User.__table__, models.Conversation.__table__
    source = _database(tmp_path / "old.db", (users, [_user("u1", "admin")]))
    target = _database(
        tmp_path / "new.db",
        (users, [_user("x", "admin")]),
        (conversations, [{"id": "c9", "owner_id": "x", "title": "t", "model": "m"}]),
    )

    with pytest.raises(DataCopyError):
        DatabaseCopier(source, target).copy()
    assert _count(target, conversations) == 1


def test_copying_onto_the_database_in_use_is_refused(tmp_path):
    with pytest.raises(DataCopyError):
        DatabaseCopier("sqlite:///same.db", "sqlite:///same.db")


def test_progress_counts_every_row_and_a_failed_copy_leaves_the_target_empty(tmp_path, monkeypatch):
    users, conversations = models.User.__table__, models.Conversation.__table__
    source = _database(
        tmp_path / "old.db",
        (users, [_user("u1", "admin")]),
        (conversations, [{"id": f"c{i}", "owner_id": "u1", "title": "t", "model": "m"} for i in range(3)]),
    )
    target = _database(tmp_path / "new.db")
    progress = CopyProgress()
    DatabaseCopier(source, target).copy(progress)
    assert progress.done == progress.total == 4

    target = _database(tmp_path / "retry.db")
    real = DatabaseCopier._copy_table

    def fail_on_conversations(read, engine, table, prog):
        if table.name == "conversations":
            raise RuntimeError("disk full")
        real(read, engine, table, prog)

    monkeypatch.setattr(DatabaseCopier, "_copy_table", staticmethod(fail_on_conversations))
    with pytest.raises(RuntimeError):
        DatabaseCopier(source, target).copy()
    assert _count(target, users) == 0  # emptied again, so a retry isn't refused


@pytest.mark.asyncio
async def test_the_job_reports_progress_then_keeps_the_result(monkeypatch):
    from app.schemas import DbActionResult, DbConfigUpdate, SqliteParams
    from app.services import db_copy_job

    async def fake_save(update, progress):
        assert update.copy_data is True
        progress.stage, progress.done, progress.total = "Copying", 5, 10
        return DbActionResult(ok=True, message="Copied 10 rows and switched")

    monkeypatch.setattr(db_copy_job.db_config_service, "save_and_apply", fake_save)
    job = db_copy_job.DatabaseCopyJob()
    update = DbConfigUpdate(db_type="sqlite", sqlite=SqliteParams(directory="/tmp", filename="x.db"))

    assert job.start(update).running is True
    await job._task
    status = job.status()
    assert status.running is False and status.ok is True and status.message.startswith("Copied 10 rows")


def test_the_running_app_can_write_to_a_sqlite_source_during_the_copy(tmp_path):
    """Regression: the copy streamed from the live file, and the app's writes between two batches of a table got
    "database is locked"."""
    import sqlite3

    users, conversations = models.User.__table__, models.Conversation.__table__
    live = tmp_path / "live.db"
    source = _database(
        live,
        (users, [_user("u1", "admin")]),
        (conversations, [{"id": f"c{i}", "owner_id": "u1", "title": "t", "model": "m"} for i in range(2000)]),
    )
    target = _database(tmp_path / "new.db")

    class WritesMidTable(CopyProgress):
        """After the first batch of conversations, while that table is still being read, the app saves."""

        wrote = False

        def __setattr__(self, name, value):
            super().__setattr__(name, value)
            if name == "done" and self.table == "conversations" and not WritesMidTable.wrote:
                WritesMidTable.wrote = True
                app_write = sqlite3.connect(live, timeout=0.1)
                app_write.execute("UPDATE users SET role = 'admin'")
                app_write.commit()  # raised "database is locked" before the snapshot
                app_write.close()

    assert DatabaseCopier(source, target).copy(WritesMidTable()) == 2001
    assert WritesMidTable.wrote
    assert not list(tmp_path.glob("pairing-copy-*"))  # the snapshot is removed
