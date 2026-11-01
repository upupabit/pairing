"""Settings > Matricxon > API key (logic: app.services.matricxon_api_key)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import MatricxonApiKeyState, MatricxonApiKeyUpdate
from app.services.auth_service import require_admin
from app.services.matricxon_api_key import MatricxonApiKey

router = APIRouter(prefix="/api/settings/matricxon/api-key", tags=["matricxon"])


@router.get("", response_model=MatricxonApiKeyState)
async def get_api_key(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonApiKeyState:
    return await MatricxonApiKey(db).state()


@router.put("", response_model=MatricxonApiKeyState)
async def set_api_key(
    body: MatricxonApiKeyUpdate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> MatricxonApiKeyState:
    return await MatricxonApiKey(db).set(body.key.strip())
