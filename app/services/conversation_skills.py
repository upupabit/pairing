"""The skills a chat uses (the chat's Skills picker, models/skill.py ConversationSkill) and their part of its
system prompt (chat_prompt_service.py). Like persona and rules notes, they change only before the first message
(the system prompt opens the conversation, so a later change re-reads all of it), and in a channel only admins and
its managers change them, from the shared library only: a member's private skill would be hidden from the others.
"""

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationSkill, Skill, User
from app.schemas.skill import ConversationSkillsOut, SkillOut
from app.services import channel_service, conversation_service
from app.services.skill_library import to_skill_out


def _usable(skill: Skill, conversation: Conversation) -> bool:
    """An enabled library skill, or in a personal chat its owner's private one."""
    if skill.owner_id is None:
        return skill.enabled
    return conversation.channel_id is None and skill.owner_id == conversation.owner_id


async def available(db: AsyncSession, user: User, conversation: Conversation | None = None) -> list[SkillOut]:
    """What the picker offers: the enabled library, plus `user`'s private skills outside a channel."""
    private = conversation is None or conversation.channel_id is None
    condition = Skill.owner_id.is_(None) & Skill.enabled
    if private:
        condition = or_(condition, Skill.owner_id == user.id)
    rows = (await db.execute(select(Skill).where(condition).order_by(Skill.category, Skill.name))).scalars().all()
    return [to_skill_out(s) for s in rows]


async def active_skills(db: AsyncSession, conversation: Conversation) -> list[Skill]:
    """The chosen skills that still apply (a disabled or no longer reachable one is skipped), in the order chosen."""
    choices = (
        (
            await db.execute(
                select(ConversationSkill)
                .where(ConversationSkill.conversation_id == conversation.id)
                .order_by(ConversationSkill.created_at, ConversationSkill.id)
            )
        )
        .scalars()
        .all()
    )
    return [c.skill for c in choices if _usable(c.skill, conversation)]


def build_skills_prompt(skills: list[Skill]) -> str:
    """Each skill under its name, after persona and rules in the system prompt."""
    blocks = [f"## {s.name}\n{s.content.strip()}" for s in skills]
    return "Skills for this conversation (follow the one that fits the request):\n\n" + "\n\n".join(blocks)


def edit_block_reason(conversation: Conversation, user: User) -> str | None:
    """Why `user` can't change this chat's skills now, or None."""
    if conversation_service.visible_messages(conversation):
        return "Skills can only change before the first message."
    if conversation.channel_id is not None and not channel_service.can_manage_channel_conversation(conversation, user):
        return "Only admins and this channel's managers can change its skills."
    return None


async def chosen(db: AsyncSession, conversation: Conversation, user: User) -> ConversationSkillsOut:
    skills = await active_skills(db, conversation)
    reason = edit_block_reason(conversation, user)
    return ConversationSkillsOut(chosen=[to_skill_out(s) for s in skills], editable=reason is None, reason=reason)


async def choose(
    db: AsyncSession, conversation: Conversation, user: User, skill_ids: list[str]
) -> ConversationSkillsOut:
    """Replaces the chat's skills with `skill_ids`, in that order. 409 when locked, 404 for a skill it can't use."""
    if reason := edit_block_reason(conversation, user):
        status = 409 if conversation_service.visible_messages(conversation) else 403
        raise HTTPException(status_code=status, detail=reason)
    wanted = list(dict.fromkeys(skill_ids))
    skills = (
        {s.id: s for s in (await db.execute(select(Skill).where(Skill.id.in_(wanted)))).scalars().all()}
        if wanted
        else {}
    )
    usable = {s.id for s in await available(db, user, conversation)}
    if any(skill_id not in skills or skill_id not in usable for skill_id in wanted):
        raise HTTPException(status_code=404, detail="Skill not found")
    for choice in list(conversation.skill_choices):
        await db.delete(choice)
    await db.flush()
    for skill_id in wanted:
        db.add(ConversationSkill(conversation_id=conversation.id, skill_id=skill_id))
        await db.flush()  # one created_at each, so the order holds
    await db.commit()
    await db.refresh(conversation, ["skill_choices"])
    return await chosen(db, conversation, user)
