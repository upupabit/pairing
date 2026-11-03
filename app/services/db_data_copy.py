"""Copies every pAIring table from the current database into a new one when switching (Admin settings > System >
Database, "Copy my data"). The target must be fresh: only the starter data a schema build adds, which is
replaced. Sync code, run in a thread like database._run_migrations.

Built for big tables: rows are streamed from the source (a server-side cursor on MySQL, so a table is never held
in memory) and written in batches, one commit per table. A failure empties the target again, so a retry is not
refused as "already has data". MySQL's foreign-key checks are off during the copy, for rows that point at their
own table (a reply's message). `CopyProgress` tells Settings how far it got.

A SQLite source is first snapshotted (SQLite's backup, in small steps): a long read on the live file would block
every write of the running app ("database is locked"), and the snapshot is one consistent point in time.
"""

import contextlib
import sqlite3
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Connection, Engine, make_url

from app.database import Base

BATCH = 500
# Any of these holding rows means the target has its own data, which a copy must never overwrite.
_USER_DATA_TABLES = ("conversations", "documents", "channels")


class DataCopyError(ValueError):
    """Shown to the admin; nothing was copied."""


@dataclass
class CopyProgress:
    """Written by the copy's thread, read by status polls; plain fields, so no lock is needed."""

    stage: str = "Starting"
    table: str | None = None
    done: int = 0
    total: int = 0


class DatabaseCopier:
    def __init__(self, source_url: str, target_url: str) -> None:
        if source_url == target_url:
            raise DataCopyError("The new database is the one in use now.")
        self._source_url = source_url
        self._target_url = target_url

    def copy(self, progress: CopyProgress | None = None) -> int:
        """Returns the number of rows copied."""
        from app import models  # noqa: F401 - registers every table on Base.metadata

        progress = progress or CopyProgress()
        with self._readable_source(progress) as source_url:
            return self._copy_from(source_url, progress)

    def _copy_from(self, source_url: str, progress: CopyProgress) -> int:
        tables = Base.metadata.sorted_tables
        source = create_engine(source_url)
        target = create_engine(self._target_url)
        try:
            with source.connect() as read:
                with target.begin() as write:
                    self._check_fresh(write, tables)
                progress.stage = "Counting rows"
                progress.total = sum(read.execute(select(func.count()).select_from(t)).scalar() for t in tables)
                try:
                    self._clear(target, tables)
                    for table in tables:
                        progress.stage, progress.table = "Copying", table.name
                        self._copy_table(read, target, table, progress)
                except Exception:
                    self._clear(target, tables)
                    raise
            return progress.done
        finally:
            source.dispose()
            target.dispose()

    @contextlib.contextmanager
    def _readable_source(self, progress: CopyProgress) -> Iterator[str]:
        url = make_url(self._source_url)
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            yield self._source_url
            return
        live = Path(url.database)
        progress.stage = "Taking a snapshot"
        with tempfile.TemporaryDirectory(prefix="pairing-copy-", dir=live.parent) as folder:
            snapshot = Path(folder) / "snapshot.db"
            source, copy = sqlite3.connect(live), sqlite3.connect(snapshot)
            try:
                source.backup(copy, pages=256, sleep=0.005)  # lets the app write between steps
            finally:
                copy.close()
                source.close()
            yield f"sqlite:///{snapshot}"

    @staticmethod
    def _copy_table(read: Connection, target: Engine, table, progress: CopyProgress) -> None:
        rows = read.execution_options(stream_results=True).execute(select(table)).mappings()
        with target.begin() as write:
            if target.dialect.name == "mysql":
                write.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            while batch := [dict(row) for row in rows.fetchmany(BATCH)]:
                write.execute(table.insert(), batch)
                progress.done += len(batch)

    @staticmethod
    def _clear(target: Engine, tables) -> None:
        with target.begin() as write:
            if target.dialect.name == "mysql":
                write.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in reversed(tables):
                write.execute(table.delete())

    @staticmethod
    def _check_fresh(write: Connection, tables) -> None:
        by_name = {t.name: t for t in tables}
        busy = [n for n in _USER_DATA_TABLES if write.execute(select(func.count()).select_from(by_name[n])).scalar()]
        users = write.execute(select(func.count()).select_from(by_name["users"])).scalar()
        if busy or users > 1:
            raise DataCopyError(
                "The new database already has its own data (" + ", ".join(busy or ["users"]) + "). "
                "Copy only into an empty database, or empty it first."
            )
