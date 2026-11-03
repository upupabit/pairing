"""A reply's speed (messages.stats): time to first token, tokens/sec

Revision ID: b7d2f4a6c8e1
Revises: a3c5e7b9d1f2
"""

import sqlalchemy as sa

from alembic import op

revision = "b7d2f4a6c8e1"
down_revision = "a3c5e7b9d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("stats", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "stats")
