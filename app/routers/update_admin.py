"""Admin settings > Update: check for and apply updates to pAIring and a local Matricxon (SSE progress)."""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import OkResponse
from app.schemas.update import UpdateOverview, UpdateSourceIn, UpdateSourceOut, UpdateTokenIn
from app.services import http_proxy_service, settings_service
from app.services.auth_service import require_admin
from app.services.extended_model_catalog_service import ExtendedModelCatalog
from app.services.update_source import UpdateSourceError, UpdateSourceService
from app.services.update_targets import MatricxonUpdate, PairingUpdate

router = APIRouter(prefix="/api/settings/update", tags=["update"])


async def _proxy_url(db: AsyncSession) -> str | None:
    return (await http_proxy_service.get_http_proxy_config(db)).proxy_url()


def _sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        async for event in events:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/status", response_model=UpdateOverview)
async def status(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> UpdateOverview:
    proxy_url = await _proxy_url(db)
    sources = UpdateSourceService(db)
    pairing = PairingUpdate(proxy_url, remote=await sources.remote("pairing"), token=await sources.token("pairing"))
    config = await settings_service.get_matricxon_server_config(db)
    remote, token = await sources.remote("matricxon"), await sources.token("matricxon")
    matricxon = MatricxonUpdate(config, proxy_url, remote, token)
    return UpdateOverview(
        pairing=await pairing.status(), matricxon=await matricxon.status(), restart=pairing.restart_info()
    )


@router.post("/pairing")
async def update_pairing(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> StreamingResponse:
    sources = UpdateSourceService(db)
    remote, token = await sources.remote("pairing"), await sources.token("pairing")
    pairing = PairingUpdate(await _proxy_url(db), remote=remote, token=token)
    if pairing.in_container():
        raise HTTPException(status_code=400, detail="Running in a container: update by pulling a new image.")
    return _sse(pairing.updater.update_stream())


@router.post("/matricxon")
async def update_matricxon(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> StreamingResponse:
    config = await settings_service.get_matricxon_server_config(db)
    sources = UpdateSourceService(db)
    remote, token = await sources.remote("matricxon"), await sources.token("matricxon")
    matricxon = MatricxonUpdate(config, await _proxy_url(db), remote, token)
    if matricxon.updater is None:
        raise HTTPException(status_code=400, detail="Matricxon is not installed locally.")
    # Read before streaming: the session closes once the response starts.
    await ExtendedModelCatalog(db).clear()
    return _sse(matricxon.update_stream())


@router.post("/pairing/restart", response_model=OkResponse)
async def restart_pairing(_admin: User = Depends(require_admin)) -> OkResponse:
    try:
        PairingUpdate().restart()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OkResponse()


@router.get("/source/{product}", response_model=UpdateSourceOut)
async def get_source(
    product: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> UpdateSourceOut:
    try:
        return await UpdateSourceService(db).get(product)
    except UpdateSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/source/{product}", response_model=UpdateSourceOut)
async def save_source(
    product: str, body: UpdateSourceIn, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> UpdateSourceOut:
    try:
        return await UpdateSourceService(db).save(product, body)
    except UpdateSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/source/{product}/token", response_model=UpdateSourceOut)
async def save_token(
    product: str, body: UpdateTokenIn, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> UpdateSourceOut:
    """The access token alone (the engine page's install form); empty removes it."""
    try:
        return await UpdateSourceService(db).save_token(product, body.token)
    except UpdateSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
