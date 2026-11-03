"""Cluster > Matricxon > Update nodes: "Update all nodes" (services/matricxon_rollout.py). Admins only."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.matricxon_rollout import MatricxonRolloutOverview, NodeVersion
from app.services.auth_service import require_admin
from app.services.matricxon_rollout import matricxon_rollout
from app.services.rolling_update import RolloutError

router = APIRouter(prefix="/api/cluster/update-all", tags=["cluster"])


@router.get("", response_model=MatricxonRolloutOverview)
async def get_update_all(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonRolloutOverview:
    return await matricxon_rollout.overview(db)


@router.get("/nodes", response_model=list[NodeVersion])
async def get_node_versions(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[NodeVersion]:
    return await matricxon_rollout.node_versions(db)


@router.post("", response_model=MatricxonRolloutOverview)
async def start_update_all(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonRolloutOverview:
    try:
        await matricxon_rollout.start(db)
    except RolloutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await matricxon_rollout.overview(db)


@router.post("/cancel", response_model=MatricxonRolloutOverview)
async def cancel_update_all(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonRolloutOverview:
    await matricxon_rollout.cancel(db)
    return await matricxon_rollout.overview(db)
