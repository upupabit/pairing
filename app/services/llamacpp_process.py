"""Starts/stops the local llama-server in router mode: the supervisor behind Settings > Inference engines >
llama.cpp "local" mode. A changed local parameter restarts it (it reads its arguments only at startup),
interrupting in-flight replies; model changes don't (llamacpp_admin reloads the preset instead).

Tracked by pid in data/llamacpp.json (tracked_process), not by name: the router's per-model child processes are
also `llama-server`. It runs in its own session, so stopping it signals the whole group, children included.

Only the primary (app.config.IS_PRIMARY) may start/stop it, as sdcpp_service.py.
"""

import asyncio
import json
import logging
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import httpx

from app.config import DATA_DIR, EXTERNAL_DIR, IS_PRIMARY
from app.schemas import LlamaCppServerConfig, LlamaCppServerStatus
from app.services import llamacpp_preset, tracked_process
from app.services.llamacpp_pool import LOCAL_LLAMACPP_HOST, LOCAL_LLAMACPP_PORT

logger = logging.getLogger("llama_chat")

BINARY_NAME = "llama-server"
MANAGED_BINARY = EXTERNAL_DIR / "llama.cpp" / BINARY_NAME
_FALLBACK_BIN_PATHS = (os.path.expanduser(f"~/bin/{BINARY_NAME}"), f"/usr/local/bin/{BINARY_NAME}", str(MANAGED_BINARY))
_TRACKING_FILE = DATA_DIR / "llamacpp.json"
_LOG_PATH = DATA_DIR / "logs" / "llamacpp.log"
_START_TIMEOUT_SECONDS = 30.0
_HEALTH_CHECK_TIMEOUT = httpx.Timeout(3.0, connect=2.0)

# A Start/Stop must not interleave with a status poll or another start/stop.
_lock = asyncio.Lock()


def find_binary(binary_path: str | None = None) -> str | None:
    """The admin's override first, then PATH, ~/bin, /usr/local/bin and the managed install (llamacpp_installer)."""
    if binary_path and os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path
    found = shutil.which(BINARY_NAME)
    if found:
        return found
    return next((p for p in _FALLBACK_BIN_PATHS if os.path.isfile(p) and os.access(p, os.X_OK)), None)


def is_installed(binary_path: str | None = None) -> bool:
    return find_binary(binary_path) is not None


def build_argv(binary: str, config: LlamaCppServerConfig) -> list[str]:
    """Router mode: no model on the command line, models come from the preset."""
    preset = llamacpp_preset.PRESET_PATH
    argv = [binary, "--host", "127.0.0.1", "--port", str(LOCAL_LLAMACPP_PORT), "--models-preset", str(preset)]
    argv += ["--parallel", str(config.num_parallel or 1)]
    if config.max_loaded_models is not None:
        argv += ["--models-max", str(config.max_loaded_models)]
    if config.idle_unload_seconds:
        argv += ["--sleep-idle-seconds", str(config.idle_unload_seconds)]
    if config.gpu_layers is not None:
        argv += ["--n-gpu-layers", str(config.gpu_layers)]
    return argv + shlex.split(config.extra_args or "")


def _read_tracking() -> dict | None:
    try:
        return json.loads(_TRACKING_FILE.read_text())
    except (OSError, ValueError):
        return None


def _running_pid() -> int | None:
    info = _read_tracking()
    if info and tracked_process.is_alive(info["pid"], info["binary"]):
        return info["pid"]
    return None


def _start(config: LlamaCppServerConfig, proxy_url: str | None) -> None:
    binary = find_binary(config.binary_path)
    if binary is None:
        raise RuntimeError(f"Could not find '{BINARY_NAME}' (checked the override, PATH, ~/bin, /usr/local/bin).")
    env = dict(os.environ)
    if proxy_url:  # llama-server's own downloads, if an admin uses them through extra_args
        env.update({"HTTP_PROXY": proxy_url, "HTTPS_PROXY": proxy_url})
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOG_PATH, "ab") as log_file:
        proc = subprocess.Popen(
            build_argv(binary, config),
            cwd=str(Path(binary).parent),  # its shared libraries sit beside it
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _TRACKING_FILE.write_text(json.dumps({"pid": proc.pid, "binary": binary}))


def _stop() -> None:
    info = _read_tracking()
    if info and tracked_process.is_alive(info["pid"], info["binary"]):
        tracked_process.terminate(info["pid"], info["binary"])
        try:
            os.killpg(info["pid"], signal.SIGKILL)  # any child instance left behind
        except (ProcessLookupError, PermissionError):
            pass
    _TRACKING_FILE.unlink(missing_ok=True)


async def _ping_health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT) as client:
            return (await client.get(f"{LOCAL_LLAMACPP_HOST}/health")).status_code == 200
    except httpx.HTTPError:
        return False


async def _wait_until_healthy(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _running_pid() is None:
            return False
        if await _ping_health():
            return True
        await asyncio.sleep(0.5)
    return False


async def get_status(binary_path: str | None = None) -> LlamaCppServerStatus:
    installed = is_installed(binary_path)
    pid = _running_pid()
    if pid is None:
        return LlamaCppServerStatus(running=False, installed=installed)
    return LlamaCppServerStatus(running=True, installed=installed, pid=pid, healthy=await _ping_health())


async def _launch(config: LlamaCppServerConfig, proxy_url: str | None) -> None:
    # Imported here: llamacpp_admin reaches the DB and the store, which this module doesn't otherwise need.
    from app.services import llamacpp_admin

    await llamacpp_admin.sync_preset(reload=False)
    await asyncio.to_thread(_start, config, proxy_url)
    if not await _wait_until_healthy(_START_TIMEOUT_SECONDS):
        raise RuntimeError("llama-server did not come up — check data/logs/llamacpp.log.")


async def start(config: LlamaCppServerConfig, proxy_url: str | None = None) -> LlamaCppServerStatus:
    """RuntimeError if the binary is missing or it doesn't come up; ValueError if not the primary."""
    if not IS_PRIMARY:
        raise ValueError("llama.cpp can only be managed from the primary instance.")
    async with _lock:
        if _running_pid() is None:
            logger.info("Starting llama-server...")
            await _launch(config, proxy_url)
    return await get_status(config.binary_path)


async def stop(binary_path: str | None = None) -> LlamaCppServerStatus:
    if not IS_PRIMARY:
        raise ValueError("llama.cpp can only be managed from the primary instance.")
    async with _lock:
        await asyncio.to_thread(_stop)
    return await get_status(binary_path)


async def apply_local_config(config: LlamaCppServerConfig, proxy_url: str | None = None) -> LlamaCppServerStatus:
    """Restarts with the new arguments (also starts it if it was stopped)."""
    if not IS_PRIMARY:
        raise ValueError("llama.cpp can only be managed from the primary instance.")
    async with _lock:
        await asyncio.to_thread(_stop)
        logger.info("Starting llama-server with the updated local configuration...")
        await _launch(config, proxy_url)
    return await get_status(config.binary_path)
