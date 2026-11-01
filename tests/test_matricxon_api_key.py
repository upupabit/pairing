"""The Matricxon API key: stored encrypted, never shown, sent on every call, written to the local .env."""

import httpx
import pytest

from app.models import AppSetting
from app.routers import matricxon_admin, matricxon_api_key_admin
from app.schemas import MatricxonApiKeyUpdate, MatricxonServerConfig, MatricxonServerStatus
from app.services import engine_service, matricxon_http, matricxon_process, settings_service
from app.services.sampling_extras import SamplingExtras


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    written: list[MatricxonServerConfig] = []
    monkeypatch.setattr(matricxon_process, "write_env_file", lambda config: written.append(config))

    async def stopped(_project_dir=None):
        return MatricxonServerStatus(running=False)

    monkeypatch.setattr(matricxon_process, "get_status", stopped)
    engine_service._cached_engine = engine_service.DEFAULT_ENGINE
    yield written
    matricxon_http.set_api_key(None)
    engine_service._cached_engine = engine_service.DEFAULT_ENGINE


@pytest.mark.asyncio
async def test_set_shows_only_whether_a_key_exists(db, _quiet):
    assert (await matricxon_api_key_admin.get_api_key(db=db, _admin=None)).set is False

    state = await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key="k-123"), db=db, _admin=None)

    assert state.set is True and state.local is True and state.restart_needed is False
    assert "k-123" not in state.model_dump_json()
    assert _quiet[-1].api_key == "k-123"  # written to the local .env
    config = await settings_service.get_matricxon_server_config(db)
    assert config.api_key == "k-123"


@pytest.mark.asyncio
async def test_key_is_encrypted_at_rest_and_kept_from_the_browser(db):
    await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key="k-123"), db=db, _admin=None)

    row = await db.get(AppSetting, (settings_service.SYSTEM_OWNER_ID, settings_service.MATRICXON_SERVER_CONFIG_KEY))
    assert row.value["api_key"] and row.value["api_key"] != "k-123"
    assert (await matricxon_admin.get_config(db=db, _admin=None)).api_key is None


@pytest.mark.asyncio
async def test_saving_the_main_form_keeps_the_key(db):
    await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key="k-123"), db=db, _admin=None)

    await matricxon_admin.update_config(MatricxonServerConfig(max_loaded_models=3), db=db, _admin=None)

    assert (await settings_service.get_matricxon_server_config(db)).api_key == "k-123"


@pytest.mark.asyncio
async def test_removing_and_restart_hint(db, monkeypatch):
    async def running(_project_dir=None):
        return MatricxonServerStatus(running=True)

    monkeypatch.setattr(matricxon_process, "get_status", running)
    state = await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key="k-1"), db=db, _admin=None)
    assert state.restart_needed is True
    same = await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key="k-1"), db=db, _admin=None)
    assert same.restart_needed is False  # nothing changed

    removed = await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key=""), db=db, _admin=None)
    assert removed.set is False and removed.restart_needed is True


def test_keys_with_spaces_or_commas_are_refused():
    for bad in ("two words", "a,b"):
        with pytest.raises(ValueError):
            MatricxonApiKeyUpdate(key=bad)


@pytest.mark.asyncio
async def test_every_call_carries_the_key_while_set():
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json={}))
    async with matricxon_http.client(transport=transport) as client:
        await client.get("http://n:1/api/tags")
        matricxon_http.set_api_key("k-9")
        await client.post("http://n:1/api/chat", json={})
    assert "Authorization" not in seen[0].headers
    assert seen[1].headers["Authorization"] == "Bearer k-9"


def test_only_sampling_options_that_are_on_are_sent():
    assert SamplingExtras.of({"min_p": 0.0, "presence_penalty": 0, "temperature": 1}) == {}
    assert SamplingExtras.of({"min_p": 0.05, "frequency_penalty": -0.5}) == {"min_p": 0.05, "frequency_penalty": -0.5}
    assert SamplingExtras.of({}) == {}
