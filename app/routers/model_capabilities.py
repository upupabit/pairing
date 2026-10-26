"""GET /api/settings/model-capabilities: what a model can do, for chat-page controls shown only when they apply
(the Thinking chip, chat_thinking.js)."""

from fastapi import APIRouter, Depends

from app.models import User
from app.schemas import ModelCapabilitiesResponse
from app.services.auth_service import get_current_user
from app.services.model_capabilities import model_capabilities

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/model-capabilities", response_model=ModelCapabilitiesResponse)
async def get_model_capabilities(model: str, _user: User = Depends(get_current_user)) -> ModelCapabilitiesResponse:
    return ModelCapabilitiesResponse(model=model, capabilities=await model_capabilities.of(model))
