"""Tests for services/settings_sync.py: a save on one server (one shared database) reaches the in-memory settings of
servers on other machines through the settings_version row; a server never reloads its own save."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.schemas import LlamaCppServerConfig
from app.services import llamacpp_pool, settings_service
from app.services.settings_sync import SettingsSync


def _factory(db):
    """Session factory on the test database (the same session: nothing to close between calls)."""

    @asynccontextmanager
    async def session():
        yield db

    return session


@pytest.mark.asyncio
async def test_another_servers_save_is_reloaded_and_the_own_one_is_not(db, monkeypatch) -> None:
    this, other = SettingsSync(_factory(db)), SettingsSync(_factory(db))
    reloads: list[str] = []

    async def record(_db) -> None:
        reloads.append("reload")

    monkeypatch.setattr(SettingsSync, "_reload", staticmethod(record))

    assert await this.check() is False  # first look: startup already loaded everything
    await this.bump()
    assert await this.check() is False and reloads == []

    await other.bump()
    assert await this.check() is True and reloads == ["reload"]
    assert await this.check() is False


@pytest.mark.asyncio
async def test_a_reload_applies_the_saved_host_list(db, monkeypatch) -> None:
    this, other = SettingsSync(_factory(db)), SettingsSync(_factory(db))
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())
    await this.check()

    remote = LlamaCppServerConfig(mode="remote", remote_hosts=["http://gpu-box:8091"])
    await settings_service.set_llamacpp_server_config(db, remote)
    await other.bump()
    assert llamacpp_pool.get_effective_hosts() != ["http://gpu-box:8091"]

    assert await this.check() is True
    assert llamacpp_pool.get_effective_hosts() == ["http://gpu-box:8091"]
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())


@pytest.mark.asyncio
async def test_a_failed_check_does_not_stop_the_loop(monkeypatch) -> None:
    sync = SettingsSync()
    survived = asyncio.Event()
    calls: list[int] = []

    async def failing_once() -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database locked")
        survived.set()
        return False

    monkeypatch.setattr(sync, "check", failing_once)
    monkeypatch.setattr(SettingsSync, "POLL_SECONDS", 0.0)
    sync.start()
    await asyncio.wait_for(survived.wait(), timeout=5)
    await sync.stop()
    assert len(calls) >= 2
