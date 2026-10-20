"""Tests for Azure OpenAI (azure_client, on openai_compatible.OpenAICompatibleProvider).
httpx.AsyncClient gets a MockTransport: no network."""

import json

import httpx
import pytest

from app.services import azure_client, connector_config_cache
from app.services.azure_client import AzureError, AzureProvider
from app.services.connectors import get_connector
from app.services.engines.registry import registry

PARAMS = {"temperature": 0.5, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_predict": 64, "seed": 7}
SSE = 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
REAL_CLIENT = httpx.AsyncClient
CONFIG = {
    "endpoint": "https://my-res.openai.azure.com/",
    "api_key": "secret",
    "deployments": "gpt-4.1-mini, o4-mini",
    "embedding_deployments": "text-embedding-3-small",
}


@pytest.fixture(autouse=True)
def ready():
    connector_config_cache._cache = {
        "azure": {"config": dict(CONFIG), "enabled": True, "configured": True, "last_test_passed": True}
    }
    azure_client.PROVIDER._no_sampling.clear()
    yield
    connector_config_cache._cache = {}


def _fake_api(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(record), **kw))
    return seen


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://my-res.openai.azure.com",
        "https://my-res.openai.azure.com/",
        "https://my-res.openai.azure.com/openai/v1/",
        "https://my-res.openai.azure.com/openai",
    ],
)
def test_the_endpoint_becomes_the_v1_base_however_it_is_pasted(endpoint):
    assert AzureProvider.api_base({"endpoint": endpoint}) == "https://my-res.openai.azure.com/openai/v1"


@pytest.mark.asyncio
async def test_models_are_the_saved_deployment_names():
    models = {m["name"]: m["capabilities"] for m in await azure_client.PROVIDER.list_models()}
    assert models == {
        "gpt-4.1-mini": ["completion"],
        "o4-mini": ["completion"],
        "text-embedding-3-small": ["embedding"],
    }


@pytest.mark.asyncio
async def test_chat_calls_the_deployment_with_the_api_key_header(monkeypatch):
    seen = _fake_api(
        monkeypatch, lambda r: httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})
    )

    assert await azure_client.PROVIDER.chat_once("gpt-4.1-mini", [{"role": "user", "content": "hi"}], PARAMS) == "Hi"

    [request] = seen
    assert str(request.url) == "https://my-res.openai.azure.com/openai/v1/chat/completions"
    assert request.headers["api-key"] == "secret" and "authorization" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "gpt-4.1-mini" and body["temperature"] == 0.5


@pytest.mark.asyncio
async def test_a_reasoning_deployment_is_retried_without_sampling_settings(monkeypatch):
    def handler(request):
        if "temperature" in json.loads(request.content):
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'temperature'"}})
        return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})

    seen = _fake_api(monkeypatch, handler)

    assert await azure_client.PROVIDER.chat_once("o4-mini", [{"role": "user", "content": "hi"}], PARAMS) == "Hi"
    assert len(seen) == 2
    # Remembered: the next call goes without them at once.
    await azure_client.PROVIDER.chat_once("o4-mini", [{"role": "user", "content": "hi"}], PARAMS)
    assert len(seen) == 3


@pytest.mark.asyncio
async def test_a_missing_deployment_gets_a_clear_message(monkeypatch):
    _fake_api(monkeypatch, lambda r: httpx.Response(404, json={"error": {"code": "DeploymentNotFound"}}))

    with pytest.raises(AzureError, match='no deployment named "gpt-x"'):
        await azure_client.PROVIDER.chat_once("gpt-x", [{"role": "user", "content": "hi"}], PARAMS)


@pytest.mark.asyncio
async def test_embeddings_use_the_v1_endpoint(monkeypatch):
    seen = _fake_api(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}))

    assert await registry.get("azure").embed("hello", "text-embedding-3-small") == [0.1, 0.2]
    assert str(seen[0].url) == "https://my-res.openai.azure.com/openai/v1/embeddings"


@pytest.mark.asyncio
async def test_test_connection_checks_endpoint_deployments_and_key(monkeypatch):
    provider = azure_client.PROVIDER
    assert (await provider.test_connection({**CONFIG, "endpoint": "my-res"}))[0] is False
    assert (await provider.test_connection({**CONFIG, "deployments": " , "}))[0] is False

    _fake_api(monkeypatch, lambda r: httpx.Response(401))
    ok, message = await provider.test_connection(CONFIG)
    assert not ok and "rejected the API key" in message

    seen = _fake_api(monkeypatch, lambda r: httpx.Response(200, json={"data": []}))
    assert (await provider.test_connection(CONFIG))[0] is True
    assert str(seen[0].url) == "https://my-res.openai.azure.com/openai/v1/models"


def test_the_connector_and_engine_are_registered():
    connector = get_connector("azure")
    assert connector.engine_name == "azure" and "azure" in registry.names()
    secret_fields = {f.name for f in connector.config_fields if f.secret}
    assert secret_fields == {"api_key"}
