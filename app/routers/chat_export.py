"""Download a chat as Markdown (services/chat_export.py)."""

from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services import conversation_service
from app.services.auth_service import get_current_user
from app.services.chat_export import ChatExport

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("/{conversation_id}/export", response_class=PlainTextResponse)
async def export_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlainTextResponse:
    conversation = await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)
    export = ChatExport(conversation)
    # filename* keeps a Hebrew title readable; the plain one is a fallback.
    disposition = f"attachment; filename=\"chat.md\"; filename*=UTF-8''{quote(export.filename('md'))}"
    return PlainTextResponse(
        export.markdown(), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": disposition}
    )
