"""Tests for routers/llamacpp_admin.py, called directly (not via TestClient), like test_matricxon_admin_router.py."""

import pytest
from fastapi import HTTPException

from app.config import LLAMACPP_GITHUB_REPO, LLAMACPP_PINNED_VERSION
from app.routers import llamacpp_admin
from app.schemas import LlamaCppServerConfig, LlamaCppServerStatus
from app.services import llamacpp_pool, llamacpp_process, server_pool_broadcast


class _FakeRequest:
    def __init__(self, host):
        self.client = type("Client", (), {"host": host})()


@pytest.fixture(autouse=True)
def _no_broadcast(monkeypatch):
    async def none(_path):
        return []

    monkeypatch.setattr(server_pool_broadcast, "broadcast_refresh", none)
    yield
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())


@pytest.mark.asyncio
async def test_update_config_saves_and_refreshes_the_pool_without_restarting(db, monkeypatch):
    monkeypatch.setattr(llamacpp_process, "apply_local_config", lambda *_a, **_kw: pytest.fail("must not restart"))
    body = LlamaCppServerConfig(mode="remote", remote_hosts=["http://gpu:8080"])

    await llamacpp_admin.update_config(body, db=db, _admin=None)

    assert (await llamacpp_admin.get_config(db=db, _admin=None)).remote_hosts == ["http://gpu:8080"]
    assert llamacpp_pool.get_effective_hosts() == ["http://gpu:8080"]


@pytest.mark.asyncio
async def test_apply_restarts_with_the_saved_config(db, monkeypatch):
    seen = {}

    async def fake_apply(config, proxy_url=None):
        seen["config"] = config
        return LlamaCppServerStatus(running=True, installed=True, pid=1, healthy=True)

    monkeypatch.setattr(llamacpp_process, "apply_local_config", fake_apply)

    status = await llamacpp_admin.apply_config(LlamaCppServerConfig(num_parallel=2), db=db, _admin=None)

    assert status.running is True
    assert seen["config"].num_parallel == 2


@pytest.mark.asyncio
async def test_a_failed_start_becomes_a_502(db, monkeypatch):
    async def fail(*_a, **_kw):
        raise RuntimeError("llama-server did not come up")

    monkeypatch.setattr(llamacpp_process, "start", fail)

    with pytest.raises(HTTPException) as exc:
        await llamacpp_admin.start(db=db, _admin=None)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_internal_refresh_is_loopback_only(db):
    with pytest.raises(HTTPException) as exc:
        await llamacpp_admin.internal_refresh(_FakeRequest("10.0.0.9"), db=db)
    assert exc.value.status_code == 403

    assert (await llamacpp_admin.internal_refresh(_FakeRequest("127.0.0.1"), db=db)).ok is True


@pytest.mark.asyncio
async def test_install_defaults_name_the_pinned_release():
    defaults = await llamacpp_admin.install_defaults(_admin=None)

    assert (defaults.repo, defaults.version) == (LLAMACPP_GITHUB_REPO, LLAMACPP_PINNED_VERSION)


@pytest.mark.asyncio
async def test_auto_detected_path_shares_matricxons_folder_when_it_has_one(db, monkeypatch, tmp_path):
    from app.schemas import MatricxonServerConfig
    from app.services import settings_service

    await settings_service.set_matricxon_server_config(db, MatricxonServerConfig(models_path=str(tmp_path)))

    detected = await llamacpp_admin.auto_detected_path(_admin=None)

    assert detected.models_path == str(tmp_path)
