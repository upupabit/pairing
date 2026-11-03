"""Cluster > Servers: the server list, "Update all servers", the multi-server checks and this server's
folders and SECRET_KEY (services/servers_overview.py, servers_check.py, this_server_settings.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import OkResponse
from app.schemas.servers import ServerChecks, ServersOverview, ThisServerSettings, ThisServerUpdate
from app.services.auth_service import require_admin
from app.services.rolling_update import RolloutError
from app.services.server_registry import server_registry
from app.services.servers_check import servers_check
from app.services.servers_overview import servers_overview
from app.services.this_server_settings import ThisServerSettingsError, this_server_settings

router = APIRouter(prefix="/api/settings/servers", tags=["servers"])


@router.get("", response_model=ServersOverview)
async def list_servers(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> ServersOverview:
    return await servers_overview.overview(db)


@router.post("/update-all", response_model=ServersOverview)
async def update_all(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> ServersOverview:
    try:
        return await servers_overview.start_update_all(db)
    except RolloutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/update-all/cancel", response_model=ServersOverview)
async def cancel_update_all(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ServersOverview:
    return await servers_overview.cancel_update_all(db)


@router.get("/checks", response_model=ServerChecks)
async def checks(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> ServerChecks:
    return await servers_check.run(db)


@router.get("/this", response_model=ThisServerSettings)
async def this_server(_admin: User = Depends(require_admin)) -> ThisServerSettings:
    return this_server_settings.current()


@router.put("/this", response_model=ThisServerSettings)
async def save_this_server(body: ThisServerUpdate, _admin: User = Depends(require_admin)) -> ThisServerSettings:
    try:
        return this_server_settings.save(body)
    except ThisServerSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{server_id}", response_model=OkResponse)
async def forget_server(
    server_id: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> OkResponse:
    if not await server_registry.forget(db, server_id):
        raise HTTPException(status_code=409, detail="That server is online; stop it first.")
    return OkResponse()
