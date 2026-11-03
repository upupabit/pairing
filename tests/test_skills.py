"""Skills: the bundled template gallery, the admins' library and users' private skills (services/skill_library.py,
skill_templates.py), and the skills a chat uses (services/conversation_skills.py)."""

import pytest
from fastapi import HTTPException

from app.models import Conversation, Message, Skill
from app.schemas.skill import SkillIn, SkillTemplateAdd
from app.services import conversation_skills
from app.services.skill_library import SkillLibrary
from app.services.skill_templates import skill_templates


def _skill(name: str, content: str = "Do it well.", **extra) -> SkillIn:
    return SkillIn(name=name, content=content, **extra)


async def _chat(db, owner, channel_id: str | None = None) -> Conversation:
    conversation = Conversation(owner_id=owner.id, params={}, channel_id=channel_id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation, ["messages", "skill_choices"])
    return conversation


def test_the_bundled_gallery_has_the_fabric_templates_by_category():
    templates = skill_templates.all()
    assert len(templates) >= 200 and all(t.content and t.name and t.categories for t in templates)
    assert {"Analysis", "Writing", "Security"} <= set(skill_templates.categories())
    assert skill_templates.sources()[0]["license"] == "MIT"
    summarize = skill_templates.search("summarize")
    assert summarize and "summar" in summarize[0].name.lower()  # a name match comes first
    assert all("Security" in t.categories for t in skill_templates.search(category="Security"))


@pytest.mark.asyncio
async def test_templates_are_added_once_and_marked_as_added(db):
    library = SkillLibrary(db)
    key = skill_templates.search("summarize")[0].key

    first = await library.add_templates(SkillTemplateAdd(keys=[key]))
    again = await library.add_templates(SkillTemplateAdd(keys=[key]))

    assert (first.added, again.added, again.already) == (1, 0, 1)
    page = await library.templates("summarize")
    assert next(t for t in page.items if t.key == key).added
    [skill] = await library.list()
    assert skill.source == "fabric" and skill.enabled and not skill.private


@pytest.mark.asyncio
async def test_a_whole_category_can_be_added_at_once(db):
    result = await SkillLibrary(db).add_templates(SkillTemplateAdd(category="Security"))

    assert result.added == len(skill_templates.search(category="Security")) > 0


@pytest.mark.asyncio
async def test_the_library_and_private_skills_stay_apart(db, user, admin_user):
    shared = await SkillLibrary(db).create(_skill("Shared"))
    mine = await SkillLibrary(db, owner_id=user.id).create(_skill("Mine", enabled=False))

    assert mine.private and mine.enabled  # a private skill is always usable by its owner
    assert [s.name for s in await SkillLibrary(db).list()] == ["Shared"]
    assert [s.name for s in await SkillLibrary(db, owner_id=admin_user.id).list()] == []
    with pytest.raises(HTTPException) as other:
        await SkillLibrary(db, owner_id=admin_user.id).update(mine.id, _skill("Taken"))
    assert other.value.status_code == 404
    with pytest.raises(HTTPException):
        await SkillLibrary(db, owner_id=user.id).delete(shared.id)  # a user can't touch the library


@pytest.mark.asyncio
async def test_a_chat_uses_its_chosen_skills_in_order_and_skips_a_disabled_one(db, user):
    library = SkillLibrary(db)
    first = await library.create(_skill("First", "Step one."))
    second = await library.create(_skill("Second", "Step two."))
    private = await SkillLibrary(db, owner_id=user.id).create(_skill("Private", "My way."))
    chat = await _chat(db, user)

    result = await conversation_skills.choose(db, chat, user, [second.id, private.id, first.id])

    assert [s.name for s in result.chosen] == ["Second", "Private", "First"] and result.editable
    prompt = conversation_skills.build_skills_prompt(await conversation_skills.active_skills(db, chat))
    assert prompt.index("## Second") < prompt.index("## Private") < prompt.index("## First")

    await library.update(first.id, _skill("First", "Step one.", enabled=False))
    assert [s.name for s in await conversation_skills.active_skills(db, chat)] == ["Second", "Private"]


@pytest.mark.asyncio
async def test_skills_lock_at_the_first_message(db, user):
    skill = await SkillLibrary(db).create(_skill("Any"))
    chat = await _chat(db, user)
    db.add(Message(conversation_id=chat.id, role="user", content="hi", sender_id=user.id))
    await db.commit()
    await db.refresh(chat, ["messages"])

    with pytest.raises(HTTPException) as locked:
        await conversation_skills.choose(db, chat, user, [skill.id])
    assert locked.value.status_code == 409
    assert not (await conversation_skills.chosen(db, chat, user)).editable


@pytest.mark.asyncio
async def test_a_channel_offers_only_the_library_and_only_managers_choose(db, user, admin_user, channel_manager_user):
    from app.services import channel_service

    shared = await SkillLibrary(db).create(_skill("Shared"))
    private = await SkillLibrary(db, owner_id=admin_user.id).create(_skill("Admin's own"))
    from app.schemas.channel import ChannelCreate

    members = [user.id, channel_manager_user.id]
    body = ChannelCreate(name="team", member_user_ids=members, manager_user_ids=[channel_manager_user.id])
    channel = await channel_service.create_channel(db, body, admin_user)
    chat = channel.conversation
    await db.refresh(chat, ["messages", "skill_choices"])

    assert [s.name for s in await conversation_skills.available(db, admin_user, chat)] == ["Shared"]
    with pytest.raises(HTTPException) as hidden:
        await conversation_skills.choose(db, chat, admin_user, [private.id])
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as member:
        await conversation_skills.choose(db, chat, user, [shared.id])
    assert member.value.status_code == 403
    chosen = await conversation_skills.choose(db, chat, channel_manager_user, [shared.id])
    assert [s.name for s in chosen.chosen] == ["Shared"]


@pytest.mark.asyncio
async def test_deleting_a_skill_drops_it_from_chats(db, user):
    skill = await SkillLibrary(db).create(_skill("Gone soon"))
    chat = await _chat(db, user)
    await conversation_skills.choose(db, chat, user, [skill.id])

    await SkillLibrary(db).delete(skill.id)

    assert await db.get(Skill, skill.id) is None
    assert (await conversation_skills.chosen(db, chat, user)).chosen == []


@pytest.mark.asyncio
async def test_the_system_prompt_has_the_notes_then_the_skills(db, user, monkeypatch):
    from app.services import chat_prompt_service, note_service

    async def no_rag(*_args, **_kwargs):
        return []

    monkeypatch.setattr(chat_prompt_service, "retrieve_context", no_rag)
    await note_service.seed_default_notes(db, user)
    await db.commit()
    skill = await SkillLibrary(db).create(_skill("Reviewer", "Review the code."))
    chat = await _chat(db, user)
    await conversation_skills.choose(db, chat, user, [skill.id])

    prompt, *_ = await chat_prompt_service.build_system_prompt(db, chat, user, "hi", {"num_ctx": 8192}, [], [], 0)

    assert prompt.index("Persona:") < prompt.index("Rules") < prompt.index("## Reviewer\nReview the code.")


@pytest.mark.asyncio
async def test_chats_that_still_list_the_retired_skill_slot_load(db, user):
    """Regression: chats from before skills had their own feature list "skill" among their turned-off note slots,
    and the chat list (and the Notes page's chat picker) failed with a 500."""
    from fastapi.encoders import jsonable_encoder

    from app.routers import conversations
    from app.schemas import ConversationOut

    old_params = {"disabled_default_notes": ["persona", "skill"]}
    db.add(Conversation(owner_id=user.id, title="Old", model="m", params=old_params))
    await db.commit()

    rows = await conversations.list_conversations(db=db, user=user)
    [chat] = [ConversationOut.model_validate(row) for row in rows]

    assert jsonable_encoder(chat)["params"]["disabled_default_notes"] == ["persona"]
