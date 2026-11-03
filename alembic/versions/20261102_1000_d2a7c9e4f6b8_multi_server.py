"""several pAIring servers on one database: reply/job owners, leader lease, upload jobs, server list

Revision ID: d2a7c9e4f6b8
Revises: a8d4f6b1c3e5
"""

import sqlalchemy as sa

from alembic import op

revision = "d2a7c9e4f6b8"
down_revision = "a8d4f6b1c3e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows keep null: the primary's restart sweep still clears them, as before.
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("owner_server", sa.String(255), nullable=True))
    with op.batch_alter_table("image_generation_jobs") as batch:
        batch.add_column(sa.Column("owner_server", sa.String(255), nullable=True))

    leases = op.create_table(
        "leader_leases",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("holder", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.bulk_insert(leases, [{"name": "leader", "holder": None, "expires_at": 0}])

    op.create_table(
        "upload_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("owner_server", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_table(
        "servers",
        sa.Column("server_id", sa.String(255), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("git_commit", sa.String(40), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.BigInteger(), nullable=False),
        sa.Column("update_round", sa.String(64), nullable=True),
        sa.Column("update_state", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("servers")
    op.drop_table("upload_jobs")
    op.drop_table("leader_leases")
    with op.batch_alter_table("image_generation_jobs") as batch:
        batch.drop_column("owner_server")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("owner_server")
