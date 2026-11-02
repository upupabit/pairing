"""Cluster page > Non-cluster hosts (admin-only). Logic lives in app.services.cluster_outside."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.cluster_outside import OutsideHostList, OutsideRemove, OutsideRemoveResult
from app.services.auth_service import require_admin
from app.services.cluster_errors import NodeNotAllowedError
from app.services.cluster_outside import OutsideHosts

router = APIRouter(prefix="/api/cluster/outside-hosts", tags=["cluster"])


@router.get("", response_model=OutsideHostList)
async def list_outside_hosts(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> OutsideHostList:
    return await OutsideHosts(db).read()


@router.post("/remove", response_model=OutsideRemoveResult)
async def remove_outside_hosts(
    body: OutsideRemove, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> OutsideRemoveResult:
    """Removes the hosts from pAIring in one save; `reset` also makes the reachable ones fresh installs."""
    try:
        return await OutsideHosts(db).remove(body.hosts, body.reset)
    except NodeNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
