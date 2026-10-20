"""Tests for services/llamacpp_pool.py: which hosts each mode routes to, and the health probe path. Selection,
cooldown and failover are server_pool.HostPool's, tested there.
"""

import pytest

from app.schemas import LlamaCppServerConfig
from app.services import llamacpp_pool


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())


def test_local_mode_routes_to_the_managed_router_only():
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig(remote_hosts=["http://gpu:8080"]))

    assert llamacpp_pool.get_effective_hosts() == ["http://127.0.0.1:8091"]
    assert llamacpp_pool.is_local() is True


def test_remote_mode_routes_to_the_admins_hosts():
    hosts = ["http://gpu-a:8080", "http://gpu-b:8080"]
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig(mode="remote", remote_hosts=hosts))

    assert llamacpp_pool.get_effective_hosts() == hosts
    assert llamacpp_pool.is_local() is False
    assert llamacpp_pool.pick_host() in hosts


@pytest.mark.asyncio
async def test_check_host_probes_llama_servers_health_endpoint(monkeypatch):
    seen = {}

    async def fake_ping(host, _timeout, path="/"):
        seen["url"] = host + path
        return True

    monkeypatch.setattr(llamacpp_pool, "ping_host", fake_ping)

    assert await llamacpp_pool.check_host("http://gpu:8080") is True
    assert seen["url"] == "http://gpu:8080/health"
