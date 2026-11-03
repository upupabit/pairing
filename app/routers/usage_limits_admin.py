"""Daily usage limits (services/usage_limits.py): the default and per-user overrides. Admin only."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.usage_limits import UsageLimits, UserUsageLimits, UserUsageOut
from app.services.auth_service import require_admin
from app.services.usage_limits import UsageLimitService

router = APIRouter(prefix="/api/admin/usage-limits", tags=["usage limits"])


async def _user_or_404(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("", response_model=UsageLimits)
async def get_defaults(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> UsageLimits:
    return await UsageLimitService(db).defaults()


@router.put("", response_model=UsageLimits)
async def set_defaults(
    body: UsageLimits, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> UsageLimits:
    return await UsageLimitService(db).set_defaults(body)


@router.get("/users/{user_id}", response_model=UserUsageOut)
async def get_user_limits(
    user_id: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> UserUsageOut:
    return await UsageLimitService(db).for_user(await _user_or_404(db, user_id))


@router.put("/users/{user_id}", response_model=UserUsageOut)
async def set_user_limits(
    user_id: str, body: UserUsageLimits, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> UserUsageOut:
    return await UsageLimitService(db).set_for_user(await _user_or_404(db, user_id), body)
