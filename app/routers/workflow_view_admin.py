"""Stats > Visual chat workflow: the admin's Simple / New view choice (workflow_view_setting.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.settings import WorkflowView
from app.services import workflow_view_setting
from app.services.auth_service import require_admin

router = APIRouter(prefix="/api/settings/workflow-view", tags=["settings"])


@router.get("", response_model=WorkflowView)
async def get_setting(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> WorkflowView:
    return WorkflowView(view=await workflow_view_setting.get_workflow_view(db))


@router.put("", response_model=WorkflowView)
async def set_setting(
    body: WorkflowView, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> WorkflowView:
    await workflow_view_setting.set_workflow_view(db, body.view)
    return body
