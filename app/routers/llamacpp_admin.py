"""Settings > Inference engines > llama.cpp admin: local-mode params or remote host list, and start/stop/status
of the local llama-server (app/services/llamacpp_process.py). Same shape as matricxon_admin.py and sdcpp_admin.py.

Not to be confused with app/services/llamacpp_admin.py (model pull/delete).
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLAMACPP_GITHUB_REPO, LLAMACPP_PINNED_VERSION
from app.database import get_db
from app.models import User
from app.schemas import (
    AvailableVersions,
    HostHealthCheck,
    InstallDefaults,
    LlamaCppAutoDetectedPath,
    LlamaCppServerConfig,
    LlamaCppServerStatus,
    OkResponse,
)
from app.services import (
    github_releases,
    http_proxy_service,
    llamacpp_admin,
    llamacpp_pool,
    llamacpp_process,
    server_pool_broadcast,
    settings_service,
)
from app.services.auth_service import require_admin
from app.services.extended_model_catalog_service import ExtendedModelCatalog
from app.services.llamacpp_installer import LlamaCppInstaller

logger = logging.getLogger("llama_chat")

router = APIRouter(prefix="/api/settings/llamacpp", tags=["llamacpp"])


async def _save_and_broadcast(db: AsyncSession, body: LlamaCppServerConfig) -> None:
    """Persists `body`, applies it to this instance's pool and best-effort broadcasts it to the other local
    instances; a sibling that fails keeps its stale host list until the next save or restart (logged).
    """
    previous = await settings_service.get_llamacpp_server_config(db)
    await settings_service.set_llamacpp_server_config(db, body)
    if previous.mode != body.mode or previous.models_path != body.models_path:
        await ExtendedModelCatalog(db).clear()
    llamacpp_pool.refresh_from_config(body)
    await llamacpp_admin.sync_preset()
    failures = await server_pool_broadcast.broadcast_refresh("/api/settings/llamacpp/internal-refresh")
    if failures:
        logger.warning("Some instances did not pick up the new llama.cpp config: %s", "; ".join(failures))


@router.get("/config", response_model=LlamaCppServerConfig)
async def get_config(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    return await settings_service.get_llamacpp_server_config(db)


@router.get("/check-host", response_model=HostHealthCheck)
async def check_host(host: str, _admin: User = Depends(require_admin)):
    """Pings `host` directly, even if unsaved, so an admin can verify a remote URL first."""
    return HostHealthCheck(host=host, healthy=await llamacpp_pool.check_host(host))


@router.get("/auto-detected-path", response_model=LlamaCppAutoDetectedPath)
async def auto_detected_path(_admin: User = Depends(require_admin)):
    """What blank binary/models paths resolve to now, ignoring saved overrides; the fields' placeholders."""
    return LlamaCppAutoDetectedPath(
        path=llamacpp_process.find_binary(), models_path=str(await llamacpp_admin.default_models_folder())
    )


@router.put("/config", response_model=LlamaCppServerConfig)
async def update_config(
    body: LlamaCppServerConfig, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
):
    """Saves without restarting a running llama-server (POST /apply does, after the frontend warns)."""
    await _save_and_broadcast(db, body)
    return body


@router.post("/apply", response_model=LlamaCppServerStatus)
async def apply_config(
    body: LlamaCppServerConfig, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
):
    """Saves `body` and restarts the local llama-server with it."""
    await _save_and_broadcast(db, body)
    proxy_config = await http_proxy_service.get_http_proxy_config(db)
    try:
        await ExtendedModelCatalog(db).clear()
        return await llamacpp_process.apply_local_config(body, proxy_url=proxy_config.proxy_url())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/internal-refresh", response_model=OkResponse)
async def internal_refresh(request: Request, db: AsyncSession = Depends(get_db)):
    """Only for another local instance's broadcast_refresh; loopback-only, and exempt from instance proxying
    (instance_proxy_http.EXEMPT_PREFIXES) so it's never forwarded.
    """
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Internal endpoint — not reachable externally.")
    llamacpp_pool.refresh_from_config(await settings_service.get_llamacpp_server_config(db))
    return OkResponse(ok=True)


@router.get("/status", response_model=LlamaCppServerStatus)
async def get_status(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    config = await settings_service.get_llamacpp_server_config(db)
    return await llamacpp_process.get_status(config.binary_path)


@router.post("/start", response_model=LlamaCppServerStatus)
async def start(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    config = await settings_service.get_llamacpp_server_config(db)
    proxy_config = await http_proxy_service.get_http_proxy_config(db)
    try:
        await ExtendedModelCatalog(db).clear()
        return await llamacpp_process.start(config, proxy_url=proxy_config.proxy_url())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stop", response_model=LlamaCppServerStatus)
async def stop(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    config = await settings_service.get_llamacpp_server_config(db)
    try:
        await ExtendedModelCatalog(db).clear()
        return await llamacpp_process.stop(config.binary_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/install-defaults", response_model=InstallDefaults)
async def install_defaults(_admin: User = Depends(require_admin)):
    return InstallDefaults(repo=LLAMACPP_GITHUB_REPO, version=LLAMACPP_PINNED_VERSION)


@router.get("/available-versions", response_model=AvailableVersions)
async def available_versions(repo: str | None = None, _admin: User = Depends(require_admin)):
    """Tags fetched live from GitHub for the version picker; a convenience, never required."""
    return AvailableVersions(versions=await github_releases.list_tags(repo or LLAMACPP_GITHUB_REPO))


@router.post("/install")
async def install(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    """Downloads and installs the pinned llama.cpp release (or the override), streaming SSE progress."""
    config = await settings_service.get_llamacpp_server_config(db)
    proxy_config = await http_proxy_service.get_http_proxy_config(db)
    installer = LlamaCppInstaller(config.install_repo, config.install_version, config.install_variant)

    async def event_stream():
        async for progress in installer.install_stream(proxy_url=proxy_config.proxy_url()):
            yield f"data: {json.dumps(progress)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
