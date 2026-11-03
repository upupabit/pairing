"""startup_service: Matricxon's .env is re-synced on startup only from a config saved in this database."""

import pytest

from app.schemas import MatricxonServerConfig
from app.services import settings_service


@pytest.mark.asyncio
async def test_a_fresh_database_has_no_saved_matricxon_config(db):
    assert not await settings_service.has_matricxon_server_config(db)

    await settings_service.set_matricxon_server_config(db, MatricxonServerConfig())

    assert await settings_service.has_matricxon_server_config(db)


def test_startup_writes_the_env_only_from_a_saved_config():
    """Regression: a fresh database's defaults ("local mode") rewrote the real Matricxon's .env at startup and
    dropped its cluster settings (shared folders, role, API keys)."""
    import inspect

    from app.services import startup_service

    source = inspect.getsource(startup_service.run_startup_tasks)
    guard = source.index("has_matricxon_server_config(db)")
    assert guard < source.index("matricxon_process.write_env_file(matricxon_config)")
