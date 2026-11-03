"""Lets one server at a time migrate a shared database (database._run_migrations). The others wait,
then find the schema current. MySQL: a named server lock. SQLite: a file lock next to the database,
which covers every process on the machine (a SQLite file can't be shared across machines anyway).
"""

import asyncio
from pathlib import Path
from types import TracebackType

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

try:
    import fcntl
except ImportError:  # Windows: no file lock, one process migrates at a time anyway
    fcntl = None


class MigrationLockTimeout(RuntimeError):
    """Another server held the lock for longer than TIMEOUT_SECONDS."""


class MigrationLock:
    NAME = "pairing-migrate"
    TIMEOUT_SECONDS = 300

    def __init__(self, database_url: str) -> None:
        self._url = make_url(database_url)
        self._engine: Engine | None = None
        self._conn: Connection | None = None
        self._file = None

    def __enter__(self) -> "MigrationLock":
        if self._url.get_backend_name() == "mysql":
            self._engine = create_engine(self._url)
            self._conn = self._engine.connect()
            got = self._conn.execute(text("SELECT GET_LOCK(:name, :t)"), {"name": self.NAME, "t": self.TIMEOUT_SECONDS})
            if got.scalar() != 1:
                self._close()
                raise MigrationLockTimeout(f"Another server is still migrating (waited {self.TIMEOUT_SECONDS}s).")
        elif fcntl and self._url.database and self._url.database != ":memory:":
            self._file = open(Path(self._url.database).with_suffix(".migrate.lock"), "w")  # noqa: SIM115
            fcntl.flock(self._file, fcntl.LOCK_EX)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._conn is not None:
            self._conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": self.NAME})
        self._close()

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        if self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None


class StartupLock:
    """MigrationLock for async code: one server at a time through migrations and the startup seeding (the
    starter admin, default notes), which would otherwise duplicate rows when servers start together."""

    def __init__(self, database_url: str) -> None:
        self._lock = MigrationLock(database_url)

    async def __aenter__(self) -> "StartupLock":
        await asyncio.to_thread(self._lock.__enter__)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await asyncio.to_thread(self._lock.__exit__, exc_type, exc, tb)
