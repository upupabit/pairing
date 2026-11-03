"""Skills an admin manages (Admin settings > Skills: the shared library, owner_id NULL) and a user's private ones
(Settings > Skills, owner_id = that user). One class for both scopes: `owner_id=None` is the library.
Adding gallery templates (skill_templates.py) copies them into the library, enabled.
"""

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationSkill, Skill
from app.schemas.skill import SkillIn, SkillOut, SkillTemplateAdd, SkillTemplateAddResult, SkillTemplatePage
from app.services.skill_templates import SkillTemplates, skill_templates


def to_skill_out(skill: Skill) -> SkillOut:
    return SkillOut(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        category=skill.category,
        content=skill.content,
        enabled=skill.enabled,
        private=skill.owner_id is not None,
        source=skill.source,
        source_key=skill.source_key,
    )


class SkillLibrary:
    def __init__(self, db: AsyncSession, owner_id: str | None = None, templates: SkillTemplates = skill_templates):
        """`owner_id`: a user's private skills; None: the shared library."""
        self._db = db
        self._owner_id = owner_id
        self._templates = templates

    async def list(self) -> list[SkillOut]:
        rows = (await self._db.execute(self._scope().order_by(Skill.category, Skill.name))).scalars().all()
        return [to_skill_out(s) for s in rows]

    async def create(self, body: SkillIn) -> SkillOut:
        skill = Skill(owner_id=self._owner_id, **self._values(body))
        self._db.add(skill)
        await self._db.commit()
        return to_skill_out(skill)

    async def update(self, skill_id: str, body: SkillIn) -> SkillOut:
        skill = await self._get_or_404(skill_id)
        for key, value in self._values(body).items():
            setattr(skill, key, value)
        await self._db.commit()
        return to_skill_out(skill)

    async def delete(self, skill_id: str) -> None:
        """Also drops it from every chat that chose it. Deleted in SQL: a skill loaded earlier in this session may
        still hold an empty `choices` list, which the ORM cascade would trust."""
        skill = await self._get_or_404(skill_id)
        await self._db.execute(delete(ConversationSkill).where(ConversationSkill.skill_id == skill.id))
        await self._db.delete(skill)
        await self._db.commit()

    async def templates(self, query: str = "", category: str | None = None) -> SkillTemplatePage:
        added = await self._added_keys()
        found = self._templates.search(query, category)
        items = [t.model_copy(update={"added": (t.source, t.key) in added}) for t in found]
        return SkillTemplatePage(
            items=items,
            total=len(items),
            categories=self._templates.categories(),
            sources=self._templates.sources(),
        )

    async def add_templates(self, body: SkillTemplateAdd) -> SkillTemplateAddResult:
        """Copies templates into the library; one already there is skipped (counted in `already`)."""
        wanted = self._templates.search(category=body.category) if body.category else []
        wanted += [t for t in self._templates.all() if t.key in set(body.keys)]
        added_keys = await self._added_keys()
        added = already = 0
        for template in {(t.source, t.key): t for t in wanted}.values():
            if (template.source, template.key) in added_keys:
                already += 1
                continue
            self._db.add(
                Skill(
                    owner_id=self._owner_id,
                    name=template.name,
                    description=template.description[:500],
                    category=template.categories[0],
                    content=template.content,
                    enabled=True,
                    source=template.source,
                    source_key=template.key,
                )
            )
            added += 1
        await self._db.commit()
        return SkillTemplateAddResult(added=added, already=already)

    def _scope(self):
        if self._owner_id is None:
            return select(Skill).where(Skill.owner_id.is_(None))
        return select(Skill).where(Skill.owner_id == self._owner_id)

    async def _get_or_404(self, skill_id: str) -> Skill:
        """404 for another scope's skill too, so ids can't be probed."""
        skill = (await self._db.execute(self._scope().where(Skill.id == skill_id))).scalar_one_or_none()
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        return skill

    async def _added_keys(self) -> set[tuple[str, str]]:
        rows = await self._db.execute(
            select(Skill.source, Skill.source_key).where(Skill.owner_id.is_(None), Skill.source.isnot(None))
        )
        return {(source, key) for source, key in rows}

    def _values(self, body: SkillIn) -> dict:
        values = body.model_dump()
        if self._owner_id is not None:
            values["enabled"] = True  # a private skill is always usable by its owner
        return values
