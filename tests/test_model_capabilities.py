"""Tests for services/model_capabilities.py and GET /api/settings/model-capabilities (the chat's Thinking chip shows
only for models that report "thinking")."""

import pytest

from app.routers import model_capabilities as router
from app.services import inference_client
from app.services.inference_client import InferenceError
from app.services.model_capabilities import ModelCapabilities

MODELS = [
    {"name": "qwen", "capabilities": ["completion", "tools", "thinking"]},
    {"name": "llama", "capabilities": ["completion", "tools"]},
    {"name": "remote"},
]


@pytest.fixture
def engine(monkeypatch) -> list[int]:
    calls: list[int] = []

    async def list_models() -> list[dict]:
        calls.append(1)
        return MODELS

    monkeypatch.setattr(inference_client, "list_models", list_models)
    return calls


@pytest.mark.asyncio
async def test_capabilities_come_from_one_cached_model_list(engine) -> None:
    caps = ModelCapabilities()

    assert "thinking" in await caps.of("qwen")
    assert "thinking" not in await caps.of("llama")
    assert await caps.of("remote") is None and await caps.of("missing") is None
    assert len(engine) == 1
    caps.forget()
    await caps.of("qwen")
    assert len(engine) == 2


@pytest.mark.asyncio
async def test_an_unreachable_engine_means_unknown(monkeypatch) -> None:
    async def down() -> list[dict]:
        raise InferenceError("down")

    monkeypatch.setattr(inference_client, "list_models", down)
    assert await ModelCapabilities().of("qwen") is None


@pytest.mark.asyncio
async def test_the_endpoint_reports_a_models_capabilities(engine, monkeypatch, user) -> None:
    monkeypatch.setattr(router, "model_capabilities", ModelCapabilities())

    response = await router.get_model_capabilities("qwen", _user=user)

    assert response.model == "qwen" and "thinking" in response.capabilities
