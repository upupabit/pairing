"""MySQL fixes: messages.reply_to_message_id ON DELETE SET NULL, image_generation_jobs.seed BIGINT

MySQL checks the reply link at once and refused to delete a message a reply still pointed at, so deleting a chat
failed. An image seed goes up to 2**32-1, too big for MySQL's signed INT. SQLite enforces neither, so it is left
as it is.

Revision ID: e4b8d1f3a6c9
Revises: d2a7c9e4f6b8
"""

import sqlalchemy as sa

from alembic import op

revision = "e4b8d1f3a6c9"
down_revision = "d2a7c9e4f6b8"
branch_labels = None
depends_on = None

_NAME = "fk_messages_reply_to_message_id_messages"


def _set(ondelete: str | None) -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    op.drop_constraint(_NAME, "messages", type_="foreignkey")
    op.create_foreign_key(_NAME, "messages", "messages", ["reply_to_message_id"], ["id"], ondelete=ondelete)


def _seed(kind: sa.types.TypeEngine) -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column("image_generation_jobs", "seed", type_=kind, existing_nullable=False)


def upgrade() -> None:
    _set("SET NULL")
    _seed(sa.BigInteger())


def downgrade() -> None:
    _seed(sa.Integer())
    _set(None)
