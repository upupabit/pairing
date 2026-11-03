"""Skill and ConversationSkill models: what a chat's replies follow for a task (services/skill_library.py,
services/conversation_skills.py). Replaced the old "skill" note slot (models/note.py keeps persona and rules)."""

from sqlalchemy import Boolean, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.models._base import ID_LEN, Timestamp, new_id, utcnow


class Skill(Base):
    """A shared skill (owner_id NULL: the admins' library, used when `enabled`) or a user's private one (owner_id
    set: only that user sees and uses it). `source`/`source_key` name the gallery template it came from, if any."""

    __tablename__ = "skills"

    id = Column(String(ID_LEN), primary_key=True, default=new_id)
    owner_id = Column(String(ID_LEN), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=False, default="")
    category = Column(String(100), nullable=False, default="Other")
    content = Column(Text, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    source = Column(String(50), nullable=True)  # "fabric"; NULL for one written here
    source_key = Column(String(255), nullable=True)
    created_at = Column(Timestamp, default=utcnow)
    updated_at = Column(Timestamp, default=utcnow, onupdate=utcnow)

    choices = relationship("ConversationSkill", back_populates="skill", cascade="all, delete-orphan", lazy="selectin")


class ConversationSkill(Base):
    """One skill chosen for one conversation (the chat's Skills picker); several per conversation."""

    __tablename__ = "conversation_skills"
    __table_args__ = (UniqueConstraint("conversation_id", "skill_id", name="uq_conversation_skill"),)

    id = Column(String(ID_LEN), primary_key=True, default=new_id)
    conversation_id = Column(String(ID_LEN), ForeignKey("conversations.id"), nullable=False, index=True)
    skill_id = Column(String(ID_LEN), ForeignKey("skills.id"), nullable=False)
    created_at = Column(Timestamp, default=utcnow)

    skill = relationship("Skill", back_populates="choices", lazy="selectin")
    conversation = relationship("Conversation", back_populates="skill_choices", lazy="selectin")
