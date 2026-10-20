"""GET /api/telemetry/{engine}/summary: per-engine call telemetry for the Stats "Telemetry" view
(telemetry_service.py). Admin-only, like stats.py. Matricxon keeps its literal route for existing callers.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import EngineName, EngineTelemetrySummary
from app.services import telemetry_service
from app.services.auth_service import require_admin

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.get("/matricxon/summary", response_model=EngineTelemetrySummary)
async def get_matricxon_summary(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)):
    return await telemetry_service.get_engine_telemetry_summary(db, "matricxon")


@router.get("/{engine}/summary", response_model=EngineTelemetrySummary)
async def get_engine_summary(
    engine: EngineName, db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)
):
    return await telemetry_service.get_engine_telemetry_summary(db, engine)
