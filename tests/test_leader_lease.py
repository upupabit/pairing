"""services/leader_lease.py: one leader among servers sharing a database, with takeover after expiry."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.leader_lease import LeaderLease

# Kept before conftest's autouse fixture replaces the property for every other test.
REAL_IS_LEADER = LeaderLease.__dict__["is_leader"]


@pytest_asyncio.fixture
async def shared_db(tmp_path, monkeypatch):
    """A database file two "servers" share, built from the models (no seeded lease row)."""
    monkeypatch.setattr(LeaderLease, "is_leader", REAL_IS_LEADER)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _server(name: str, factory) -> LeaderLease:
    """As on MySQL; the test file is SQLite, where the lease is skipped."""
    return LeaderLease(server_id=name, session_factory=factory, shared=lambda _db: True)


@pytest.mark.asyncio
async def test_on_sqlite_the_primary_leads_without_writing_a_lease(shared_db):
    lease = LeaderLease(server_id="a", session_factory=shared_db)

    assert await lease.acquire_once() is True
    async with shared_db() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM leader_leases"))).scalar() == 0


@pytest.mark.asyncio
async def test_only_one_server_holds_the_lease(shared_db):
    a, b = _server("a", shared_db), _server("b", shared_db)

    assert await a.acquire_once() is True
    assert await b.acquire_once() is False
    assert await a.acquire_once() is True  # renewing its own
    assert a.is_leader and not b.is_leader


@pytest.mark.asyncio
async def test_a_released_lease_is_taken_at_once(shared_db):
    a, b = _server("a", shared_db), _server("b", shared_db)
    await a.acquire_once()

    await a.release()

    assert a.is_leader is False
    assert await b.acquire_once() is True


@pytest.mark.asyncio
async def test_an_expired_lease_is_taken_over(shared_db):
    a, b = _server("a", shared_db), _server("b", shared_db)
    await a.acquire_once()
    async with shared_db() as db:
        await db.execute(text("UPDATE leader_leases SET expires_at = 0"))
        await db.commit()

    assert await b.acquire_once() is True
    assert await a.acquire_once() is False


@pytest.mark.asyncio
async def test_an_overdue_renewal_stops_leading_before_anyone_takes_over(shared_db, monkeypatch):
    a = _server("a", shared_db)
    await a.acquire_once()

    monkeypatch.setattr(a, "_renewed_at", a._renewed_at - LeaderLease.TTL_SECONDS - 1)

    assert a.is_leader is False


@pytest.mark.asyncio
async def test_start_and_stop_take_and_free_the_lease(shared_db):
    a, b = _server("a", shared_db), _server("b", shared_db)

    await a.start()
    assert a.is_leader
    await a.stop()

    assert await b.acquire_once() is True
