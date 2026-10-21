"""Stats > Visual chat workflow live view (services/workflow_live_service.py). Admin-only, like stats.py."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.models import User
from app.schemas.workflow_live import WorkflowLiveSnapshot
from app.services.auth_service import require_admin
from app.services.workflow_live_service import WorkflowLiveService

router = APIRouter(prefix="/api/stats/workflow/live", tags=["stats"])


@router.get("/snapshot", response_model=WorkflowLiveSnapshot)
async def get_snapshot(_admin: User = Depends(require_admin)) -> WorkflowLiveSnapshot:
    return await WorkflowLiveService().snapshot()


@router.get("", response_class=StreamingResponse)
async def stream(_admin: User = Depends(require_admin)) -> StreamingResponse:
    """SSE: one WorkflowLiveSnapshot per frame."""
    return StreamingResponse(
        WorkflowLiveService().events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
