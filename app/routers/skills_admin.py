"""Admin settings > Skills: the shared skill library and the template gallery (services/skill_library.py).
Admins only."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import OkResponse
from app.schemas.skill import SkillIn, SkillOut, SkillTemplateAdd, SkillTemplateAddResult, SkillTemplatePage
from app.services.auth_service import require_admin
from app.services.skill_library import SkillLibrary

router = APIRouter(prefix="/api/admin/skills", tags=["skills"])


@router.get("", response_model=list[SkillOut])
async def list_skills(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> list[SkillOut]:
    return await SkillLibrary(db).list()


@router.post("", response_model=SkillOut)
async def create_skill(
    body: SkillIn, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> SkillOut:
    return await SkillLibrary(db).create(body)


@router.put("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: str, body: SkillIn, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> SkillOut:
    return await SkillLibrary(db).update(skill_id, body)


@router.delete("/{skill_id}", response_model=OkResponse)
async def delete_skill(
    skill_id: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> OkResponse:
    await SkillLibrary(db).delete(skill_id)
    return OkResponse()


@router.get("/templates", response_model=SkillTemplatePage)
async def list_templates(
    q: str = "", category: str | None = None, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> SkillTemplatePage:
    return await SkillLibrary(db).templates(q, category)


@router.post("/templates/add", response_model=SkillTemplateAddResult)
async def add_templates(
    body: SkillTemplateAdd, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> SkillTemplateAddResult:
    return await SkillLibrary(db).add_templates(body)
