"""Skills: a library (Admin settings > Skills) and private ones, chosen per chat; notes keep persona and rules

The "skill" note slot is gone. Its pins are removed (the notes stay). A protected Skill note still holding the
starter text is deleted; one a user edited stays as a regular note, so nothing they wrote is lost.

Revision ID: a3c5e7b9d1f2
Revises: f6c2e8a4b1d7
"""

import sqlalchemy as sa

from alembic import op
from app.models._base import Timestamp

revision = "a3c5e7b9d1f2"
down_revision = "f6c2e8a4b1d7"
branch_labels = None
depends_on = None

# The old seed (note_service.DEFAULT_NOTE_SEEDS["skill"]): such a note was never edited.
_STARTER_SKILL_TEXT = "Writing, summarizing, brainstorming, general Q&A."


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("category", sa.String(100), nullable=False, server_default="Other"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("source_key", sa.String(255), nullable=True),
        sa.Column("created_at", Timestamp, nullable=True),
        sa.Column("updated_at", Timestamp, nullable=True),
    )
    op.create_table(
        "conversation_skills",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("conversation_id", sa.String(32), sa.ForeignKey("conversations.id"), nullable=False, index=True),
        sa.Column("skill_id", sa.String(32), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("created_at", Timestamp, nullable=True),
        sa.UniqueConstraint("conversation_id", "skill_id", name="uq_conversation_skill"),
    )
    op.execute("DELETE FROM note_pins WHERE pin_type = 'skill'")
    op.execute(
        sa.text(
            "DELETE FROM note_pins WHERE note_id IN "
            "(SELECT id FROM (SELECT id FROM notes WHERE default_type = 'skill' AND content = :starter) AS starter)"
        ).bindparams(starter=_STARTER_SKILL_TEXT)
    )
    op.execute(
        sa.text("DELETE FROM notes WHERE default_type = 'skill' AND content = :starter").bindparams(
            starter=_STARTER_SKILL_TEXT
        )
    )
    op.execute("UPDATE notes SET default_type = NULL WHERE default_type = 'skill'")


def downgrade() -> None:
    op.drop_table("conversation_skills")
    op.drop_table("skills")
