"""Tests for xAI (xai_client, on openai_compatible.OpenAICompatibleProvider). httpx.AsyncClient gets a
MockTransport: no network."""

import json

import httpx
import pytest

from app.services import connector_config_cache, xai_client
from app.services.engines.registry import registry
from app.services.xai_client import XaiError

REAL_CLIENT = httpx.AsyncClient
PARAMS = {"temperature": 0.5, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_predict": 64, "seed": 7}
SSE = 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'


@pytest.fixture(autouse=True)
def ready():
    connector_config_cache._cache = {
        "xai": {"config": {"api_key": "xai-k"}, "enabled": True, "configured": True, "last_test_passed": True}
    }
    yield
    connector_config_cache._cache = {}


def _fake_api(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(record), **kw))
    return seen


@pytest.mark.asyncio
async def test_lists_chat_models_from_language_models(monkeypatch):
    body = {
        "models": [
            {"id": "grok-4.7", "input_modalities": ["text", "image"], "output_modalities": ["text"]},
            {"id": "grok-imagine-image", "input_modalities": ["text"], "output_modalities": ["image"]},
            {"id": "grok-code-fast"},  # no modalities: kept
        ]
    }
    seen = _fake_api(monkeypatch, lambda r: httpx.Response(200, json=body))

    models = await xai_client.PROVIDER.list_models()

    assert [m["name"] for m in models] == ["grok-4.7", "grok-code-fast"]
    assert all(m["capabilities"] == ["completion"] for m in models)
    assert str(seen[0].url) == "https://api.x.ai/v1/language-models"
    assert seen[0].headers["authorization"] == "Bearer xai-k"


@pytest.mark.asyncio
async def test_also_reads_a_data_list(monkeypatch):
    _fake_api(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "grok-4.6"}]}))
    assert [m["name"] for m in await xai_client.PROVIDER.list_models()] == ["grok-4.6"]


@pytest.mark.asyncio
async def test_chat_uses_chat_completions(monkeypatch):
    seen = _fake_api(
        monkeypatch, lambda r: httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})
    )

    assert await registry.get("xai").chat_once("grok-4.7", [{"role": "user", "content": "hi"}], PARAMS) == "Hi"

    assert str(seen[0].url) == "https://api.x.ai/v1/chat/completions"
    body = json.loads(seen[0].content)
    assert body["model"] == "grok-4.7" and "max_tokens" not in body  # deprecated field never sent


@pytest.mark.asyncio
async def test_errors_are_explained(monkeypatch):
    _fake_api(monkeypatch, lambda r: httpx.Response(403, json={"error": "no credits"}))
    with pytest.raises(XaiError, match="no credits left"):
        await xai_client.PROVIDER.chat_once("grok-4.7", [{"role": "user", "content": "hi"}], PARAMS)


@pytest.mark.asyncio
async def test_test_connection(monkeypatch):
    assert (await xai_client.PROVIDER.test_connection({"api_key": ""}))[0] is False
    _fake_api(monkeypatch, lambda r: httpx.Response(401))
    ok, message = await xai_client.PROVIDER.test_connection({"api_key": "bad"})
    assert not ok and "rejected the API key" in message
    _fake_api(monkeypatch, lambda r: httpx.Response(200, json={"models": []}))
    assert (await xai_client.PROVIDER.test_connection({"api_key": "xai-k"}))[0] is True
