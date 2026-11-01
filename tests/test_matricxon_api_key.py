"""The Matricxon API key: sent to every server at once (all or nothing), stored encrypted, never shown, sent on every
call; in cluster mode set on the Cluster page."""

import json

import httpx
import pytest
from fastapi import HTTPException

from app.models import AppSetting
from app.routers import matricxon_admin, matricxon_api_key_admin
from app.schemas import MatricxonApiKeyUpdate, MatricxonServerConfig
from app.services import engine_service, matricxon_http, matricxon_pool, matricxon_process, settings_service
from app.services.cluster_errors import NodeNotAllowedError
from app.services.matricxon_key_push import MatricxonKeyPush
from app.services.sampling_extras import SamplingExtras

HOSTS = ["http://a:8420", "http://b:8420"]


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(matricxon_process, "write_env_file", lambda _config: None)
    monkeypatch.setattr(matricxon_pool, "get_effective_hosts", lambda: list(HOSTS))
    engine_service._cached_engine = engine_service.DEFAULT_ENGINE
    yield
    matricxon_http.set_api_key(None)
    engine_service._cached_engine = engine_service.DEFAULT_ENGINE


@pytest.fixture
def pushed(monkeypatch) -> list[tuple[list[str], str, str]]:
    calls: list[tuple[list[str], str, str]] = []

    async def fake_push(self, hosts, new, old):
        calls.append((hosts, new, old))

    monkeypatch.setattr(MatricxonKeyPush, "push", fake_push)
    return calls


async def _set(db, key: str):
    return await matricxon_api_key_admin.set_api_key(MatricxonApiKeyUpdate(key=key), db=db, _admin=None)


@pytest.mark.asyncio
async def test_set_sends_to_every_server_then_saves(db, pushed):
    assert (await matricxon_api_key_admin.get_api_key(db=db, _admin=None)).set is False

    state = await _set(db, "k-123")

    assert pushed == [(HOSTS, "k-123", "")]
    assert state.set is True and "k-123" not in state.model_dump_json()
    assert (await settings_service.get_matricxon_server_config(db)).api_key == "k-123"
    await _set(db, "k-123")
    assert len(pushed) == 1  # same key: nothing to send


@pytest.mark.asyncio
async def test_key_is_encrypted_at_rest_and_kept_from_the_browser(db, pushed):
    await _set(db, "k-123")

    row = await db.get(AppSetting, (settings_service.SYSTEM_OWNER_ID, settings_service.MATRICXON_SERVER_CONFIG_KEY))
    assert row.value["api_key"] and row.value["api_key"] != "k-123"
    assert (await matricxon_admin.get_config(db=db, _admin=None)).api_key is None


@pytest.mark.asyncio
async def test_saving_the_main_form_keeps_the_key(db, pushed):
    await _set(db, "k-123")
    await matricxon_admin.update_config(MatricxonServerConfig(max_loaded_models=3), db=db, _admin=None)
    assert (await settings_service.get_matricxon_server_config(db)).api_key == "k-123"


@pytest.mark.asyncio
async def test_a_refusing_server_changes_nothing(db, monkeypatch):
    async def refuse(self, hosts, new, old):
        raise NodeNotAllowedError("http://b:8420 did not accept the key")

    monkeypatch.setattr(MatricxonKeyPush, "push", refuse)
    with pytest.raises(HTTPException) as caught:
        await _set(db, "k-1")
    assert caught.value.status_code == 400
    assert (await settings_service.get_matricxon_server_config(db)).api_key is None


@pytest.mark.asyncio
async def test_cluster_mode_sets_it_on_the_cluster_page_only(db, pushed):
    config = await settings_service.get_matricxon_server_config(db)
    config.cluster_role = "seed"
    await settings_service.set_matricxon_server_config(db, config)

    with pytest.raises(HTTPException) as caught:
        await _set(db, "k-1")
    assert caught.value.status_code == 409
    state = await matricxon_api_key_admin.set_cluster_api_key(MatricxonApiKeyUpdate(key="k-1"), db=db, _admin=None)
    assert state.set is True and state.cluster is True
    assert pushed == [(HOSTS, "k-1", "")]


def test_keys_with_spaces_or_commas_are_refused():
    for bad in ("two words", "a,b"):
        with pytest.raises(ValueError):
            MatricxonApiKeyUpdate(key=bad)


class _Nodes:
    """Fake nodes: each keeps its key and accepts a change only with the key it holds."""

    def __init__(self, refuse: str = "", down: str = "") -> None:
        self.keys = {h: "old" for h in HOSTS}
        self.refuse, self.down = refuse, down

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = f"{request.url.scheme}://{request.url.host}:{request.url.port}"
        if host == self.down:
            raise httpx.ConnectError("down")
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "2.0"})
        if host == self.refuse:
            return httpx.Response(404)
        if request.headers.get("Authorization") != f"Bearer {self.keys[host]}":
            return httpx.Response(401)
        self.keys[host] = json.loads(request.content)["key"]
        return httpx.Response(200, json={"api_key": True})


@pytest.mark.asyncio
async def test_push_reaches_every_node():
    nodes = _Nodes()
    await MatricxonKeyPush(httpx.MockTransport(nodes)).push(HOSTS, "new", "old")
    assert nodes.keys == {h: "new" for h in HOSTS}


@pytest.mark.asyncio
async def test_push_puts_the_old_key_back_when_a_node_refuses():
    nodes = _Nodes(refuse=HOSTS[1])
    with pytest.raises(NodeNotAllowedError, match="update its Matricxon"):
        await MatricxonKeyPush(httpx.MockTransport(nodes)).push(HOSTS, "new", "old")
    assert nodes.keys[HOSTS[0]] == "old"  # changed, then put back with the new key


@pytest.mark.asyncio
async def test_push_changes_nothing_while_a_node_is_down():
    nodes = _Nodes(down=HOSTS[1])
    with pytest.raises(NodeNotAllowedError, match="not answering"):
        await MatricxonKeyPush(httpx.MockTransport(nodes)).push(HOSTS, "new", "old")
    assert nodes.keys[HOSTS[0]] == "old"


@pytest.mark.asyncio
async def test_every_call_carries_the_key_unless_the_caller_names_one():
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json={}))
    async with matricxon_http.client(transport=transport) as client:
        await client.get("http://n:1/api/tags")
        matricxon_http.set_api_key("k-9")
        await client.post("http://n:1/api/chat", json={})
        await client.put("http://n:1/api/cluster/api-key", json={}, headers={"Authorization": "Bearer other"})
    assert "Authorization" not in seen[0].headers
    assert seen[1].headers["Authorization"] == "Bearer k-9"
    assert seen[2].headers["Authorization"] == "Bearer other"


def test_only_sampling_options_that_are_on_are_sent():
    assert SamplingExtras.of({"min_p": 0.0, "presence_penalty": 0, "temperature": 1}) == {}
    assert SamplingExtras.of({"min_p": 0.05, "frequency_penalty": -0.5}) == {"min_p": 0.05, "frequency_penalty": -0.5}
