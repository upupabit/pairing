"""move settings from the removed Ollama engine to llama.cpp

The active engine "ollama" becomes "llamacpp", and each owner's remembered default model moves from
`default_model:ollama` to `default_model:llamacpp` (both engines use the same hf.co/<repo>:<file> tags). The old
Ollama server config is dropped: its fields don't apply to llama-server. Telemetry rows keep engine "ollama", as
history of what really served them.

Revision ID: a8d4f6b1c3e5
Revises: f7c3e5a9b2d4
"""

import sqlalchemy as sa

from alembic import op

revision = "a8d4f6b1c3e5"
down_revision = "f7c3e5a9b2d4"
branch_labels = None
depends_on = None

_settings = sa.table(
    "app_settings",
    sa.column("owner_id", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.JSON),
)


def _move_engine(old: str, new: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_settings.c.owner_id, _settings.c.value).where(_settings.c.key == "active_llm_engine")
    )
    for owner_id, value in rows.fetchall():
        if isinstance(value, dict) and value.get("engine") == old:
            bind.execute(
                _settings.update()
                .where(_settings.c.owner_id == owner_id, _settings.c.key == "active_llm_engine")
                .values(value={"engine": new})
            )
    old_key, new_key = f"default_model:{old}", f"default_model:{new}"
    taken = {
        owner_id for (owner_id,) in bind.execute(sa.select(_settings.c.owner_id).where(_settings.c.key == new_key))
    }
    for (owner_id,) in bind.execute(sa.select(_settings.c.owner_id).where(_settings.c.key == old_key)).fetchall():
        if owner_id not in taken:
            bind.execute(
                _settings.update()
                .where(_settings.c.owner_id == owner_id, _settings.c.key == old_key)
                .values(key=new_key)
            )


def upgrade() -> None:
    _move_engine("ollama", "llamacpp")
    op.execute(_settings.delete().where(_settings.c.key == "ollama_server_config"))


def downgrade() -> None:
    _move_engine("llamacpp", "ollama")
