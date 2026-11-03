"""Skills for every user: their private skills (Settings > Skills), what a chat's picker offers, and the skills a
chat uses (services/conversation_skills.py, services/skill_library.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import OkResponse
from app.schemas.skill import ConversationSkillsIn, ConversationSkillsOut, SkillIn, SkillOut
from app.services import conversation_service, conversation_skills
from app.services.auth_service import get_current_user
from app.services.skill_library import SkillLibrary

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/available", response_model=list[SkillOut])
async def available_skills(
    conversation_id: str | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[SkillOut]:
    """The picker's list: the enabled library, plus the user's private skills outside a channel."""
    conversation = (
        await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)
        if conversation_id
        else None
    )
    return await conversation_skills.available(db, user, conversation)


@router.get("/mine", response_model=list[SkillOut])
async def my_skills(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[SkillOut]:
    return await SkillLibrary(db, owner_id=user.id).list()


@router.post("/mine", response_model=SkillOut)
async def create_my_skill(
    body: SkillIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> SkillOut:
    return await SkillLibrary(db, owner_id=user.id).create(body)


@router.put("/mine/{skill_id}", response_model=SkillOut)
async def update_my_skill(
    skill_id: str, body: SkillIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> SkillOut:
    return await SkillLibrary(db, owner_id=user.id).update(skill_id, body)


@router.delete("/mine/{skill_id}", response_model=OkResponse)
async def delete_my_skill(
    skill_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> OkResponse:
    await SkillLibrary(db, owner_id=user.id).delete(skill_id)
    return OkResponse()


@router.get("/conversation/{conversation_id}", response_model=ConversationSkillsOut)
async def conversation_skills_of(
    conversation_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> ConversationSkillsOut:
    conversation = await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)
    return await conversation_skills.chosen(db, conversation, user)


@router.put("/conversation/{conversation_id}", response_model=ConversationSkillsOut)
async def choose_conversation_skills(
    conversation_id: str,
    body: ConversationSkillsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationSkillsOut:
    conversation = await conversation_service.get_accessible_conversation_or_404(db, conversation_id, user)
    return await conversation_skills.choose(db, conversation, user, body.skill_ids)
