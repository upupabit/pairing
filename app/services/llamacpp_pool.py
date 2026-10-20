"""Routes llama.cpp requests across llama-server host(s): a thin wrapper around server_pool.HostPool (selection,
cooldown, failover; shared with the other pools).

The host list is admin-configured (Settings > Inference engines, settings_service.get_llamacpp_server_config):
"local" is LOCAL_LLAMACPP_HOST alone (the router llamacpp_process.py starts), "remote" the admin's remote_hosts.
Cached via refresh_from_config, not read per chat request: loaded at startup and refreshed on every admin save.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager

import httpx

from app.schemas import LlamaCppServerConfig
from app.services.server_pool import HostPool, ping_host

# The port llamacpp_process passes to llama-server; a fixed fact, not a setting.
LOCAL_LLAMACPP_PORT = 8091
LOCAL_LLAMACPP_HOST = f"http://127.0.0.1:{LOCAL_LLAMACPP_PORT}"

_HEALTH_CHECK_TIMEOUT = httpx.Timeout(3.0, connect=2.0)
_COOLDOWN_SECONDS = 30.0
_HEALTH_PATH = "/health"

_pool = HostPool(cooldown_seconds=_COOLDOWN_SECONDS)
# Usable before the first refresh_from_config (tests and tools importing this module).
_pool.set_hosts([LOCAL_LLAMACPP_HOST])


def refresh_from_config(config: LlamaCppServerConfig) -> None:
    """Recomputes the live host list; called on admin save and at startup."""
    hosts = config.remote_hosts if config.mode == "remote" else [LOCAL_LLAMACPP_HOST]
    _pool.set_hosts(hosts)


def get_effective_hosts() -> list[str]:
    return _pool.get_hosts()


def is_local() -> bool:
    return get_effective_hosts() == [LOCAL_LLAMACPP_HOST]


def pick_host(exclude: frozenset[str] = frozenset()) -> str:
    return _pool.pick_host(exclude)


def mark_failure(host: str) -> None:
    _pool.mark_failure(host)


def mark_recovered(host: str) -> None:
    _pool.mark_recovered(host)


def track_request(host: str) -> AbstractAsyncContextManager[None]:
    return _pool.track_request(host)


async def stream_with_failover(
    make_stream: Callable[[str], AsyncGenerator[str, None]],
) -> AsyncGenerator[str, None]:
    async for chunk in _pool.stream_with_failover(make_stream):
        yield chunk


async def check_hosts() -> dict[str, bool]:
    """Pings every configured host (llama-server's `GET /health`); used by routers/health.py."""
    return await _pool.check_hosts(_HEALTH_CHECK_TIMEOUT, path=_HEALTH_PATH)


async def check_host(host: str) -> bool:
    """Same probe for one possibly unsaved host, to verify a remote URL before saving."""
    return await ping_host(host, _HEALTH_CHECK_TIMEOUT, path=_HEALTH_PATH)
