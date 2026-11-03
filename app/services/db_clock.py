"""The database's clock in epoch seconds, as SQL: servers on several machines compare times without
trusting each other's clocks (leader_lease.py, server_registry.py). And whether servers can share it at all."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def db_epoch_sql(db: AsyncSession) -> str:
    if db.get_bind().dialect.name == "mysql":
        return "UNIX_TIMESTAMP()"
    return "CAST(strftime('%s', 'now') AS INTEGER)"


async def db_epoch(db: AsyncSession) -> int:
    return int((await db.execute(text(f"SELECT {db_epoch_sql(db)}"))).scalar())


def shared_database(db: AsyncSession) -> bool:
    """False on SQLite: a local file, so this machine's processes are the only servers and the leader
    lease, heartbeats and "Update all" have nothing to coordinate."""
    return db.get_bind().dialect.name != "sqlite"
