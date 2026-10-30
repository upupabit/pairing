"""Tests for services/matricxon_autostart.py: Matricxon started with pAIring when it is the active engine and down.
Nothing is really started (matricxon_process and the settings reads are patched).
"""

from contextlib import asynccontextmanager

import pytest

from app.schemas import MatricxonServerConfig, MatricxonServerStatus
from app.services import matricxon_autostart as autostart_module
from app.services.matricxon_autostart import MatricxonAutostart


class _Proxy:
    @staticmethod
    def proxy_url() -> str | None:
        return "http://proxy:3128"


@pytest.fixture
def setup(monkeypatch):
    """Matricxon active, local, installed and stopped; each test changes one of these."""
    state = {"engine": "matricxon", "mode": "local", "installed": True, "running": False, "started": []}

    @asynccontextmanager
    async def session():
        yield None

    async def get_config(db):
        hosts = ["http://10.0.0.5:8420"] if state["mode"] == "remote" else []
        return MatricxonServerConfig(mode=state["mode"], remote_hosts=hosts)

    async def get_proxy(db):
        return _Proxy()

    async def get_status(project_dir=None):
        return MatricxonServerStatus(running=state["running"], installed=state["installed"])

    async def start(config, proxy_url=None):
        if state.get("fail"):
            raise RuntimeError("did not come up")
        state["started"].append(proxy_url)
        return MatricxonServerStatus(running=True, installed=True)

    monkeypatch.setattr(autostart_module, "MATRICXON_AUTOSTART", True)
    monkeypatch.setattr(autostart_module, "IS_PRIMARY", True)
    monkeypatch.setattr(autostart_module, "AsyncSessionLocal", session)
    monkeypatch.setattr(autostart_module.engine_service, "current_engine", lambda: state["engine"])
    monkeypatch.setattr(autostart_module.settings_service, "get_matricxon_server_config", get_config)
    monkeypatch.setattr(autostart_module.http_proxy_service, "get_http_proxy_config", get_proxy)
    monkeypatch.setattr(autostart_module.matricxon_process, "is_installed", lambda project_dir=None: state["installed"])
    monkeypatch.setattr(autostart_module.matricxon_process, "get_status", get_status)
    monkeypatch.setattr(autostart_module.matricxon_process, "start", start)
    return state


async def test_starts_when_active_local_installed_and_stopped(setup):
    wanted = await MatricxonAutostart().needed()
    assert wanted is not None and wanted[1] == "http://proxy:3128"


@pytest.mark.parametrize(
    "change", [{"engine": "llamacpp"}, {"mode": "remote"}, {"installed": False}, {"running": True}]
)
async def test_left_alone_when_not_ours_to_start(setup, change):
    setup.update(change)
    assert await MatricxonAutostart().needed() is None


async def test_off_switch_and_secondary_instances(setup, monkeypatch):
    monkeypatch.setattr(autostart_module, "MATRICXON_AUTOSTART", False)
    assert await MatricxonAutostart().needed() is None
    monkeypatch.setattr(autostart_module, "MATRICXON_AUTOSTART", True)
    monkeypatch.setattr(autostart_module, "IS_PRIMARY", False)
    assert await MatricxonAutostart().needed() is None


async def test_run_starts_then_does_the_engine_work(setup):
    done = []

    async def then():
        done.append(True)

    await MatricxonAutostart.run(MatricxonServerConfig(), "http://proxy:3128", then)
    assert setup["started"] == ["http://proxy:3128"] and done == [True]


async def test_a_failed_start_is_logged_and_skips_the_engine_work(setup, caplog):
    setup["fail"] = True
    done = []

    async def then():
        done.append(True)

    await MatricxonAutostart.run(MatricxonServerConfig(), None, then)
    assert done == [] and "Could not start Matricxon" in caplog.text
