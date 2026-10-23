"""Stats > Visual chat workflow live view (services/workflow_live_service.py). Admin-only, like stats.py."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.models import User
from app.schemas.workflow_analysis import WorkflowAnalysis
from app.schemas.workflow_live import WorkflowLiveSnapshot
from app.services.auth_service import require_admin
from app.services.workflow_analysis import WorkflowAnalyzer
from app.services.workflow_live_service import workflow_live_service

router = APIRouter(prefix="/api/stats/workflow/live", tags=["stats"])


@router.get("/snapshot", response_model=WorkflowLiveSnapshot)
async def get_snapshot(_admin: User = Depends(require_admin)) -> WorkflowLiveSnapshot:
    return await workflow_live_service.snapshot()


@router.get("", response_class=StreamingResponse)
async def stream(_admin: User = Depends(require_admin)) -> StreamingResponse:
    """SSE: one WorkflowLiveSnapshot per frame."""
    return StreamingResponse(
        workflow_live_service.events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/analysis", response_model=WorkflowAnalysis)
async def get_analysis(_admin: User = Depends(require_admin)) -> WorkflowAnalysis:
    """Stats > Workflow analysis. Also takes a sample, so the page keeps the history going on its own."""
    await workflow_live_service.frame()
    history = workflow_live_service.history
    return WorkflowAnalyzer(history.buckets(), history.WINDOW_SECONDS).report()
