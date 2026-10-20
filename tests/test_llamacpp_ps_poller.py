"""Tests for services/llamacpp_ps_poller.py. The `db` fixture patches its AsyncSessionLocal (conftest.py)."""

import httpx
import pytest
from sqlalchemy import select

from app.models import ModelSnapshot
from app.schemas import LlamaCppServerConfig
from app.services import llamacpp_pool
from app.services.llamacpp_ps_poller import LlamaCppPsPoller

_REAL_CLIENT = httpx.AsyncClient


@pytest.mark.asyncio
async def test_poll_once_records_only_loaded_models_by_their_tag(monkeypatch, db):
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig(mode="remote", remote_hosts=["http://gpu:8080"]))
    body = {
        "data": [
            {"id": "hf.co/org/a-GGUF@a-Q4_K_M", "status": {"value": "loaded"}},
            {"id": "hf.co/org/b-GGUF@b-Q4_K_M", "status": {"value": "unloaded"}},
            {"id": "hf.co/org/c-GGUF@c-Q4_K_M", "status": {"value": "sleeping"}},
        ]
    }
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _REAL_CLIENT(transport=transport))

    try:
        await LlamaCppPsPoller().poll_once()
    finally:
        llamacpp_pool.refresh_from_config(LlamaCppServerConfig())

    [row] = (await db.execute(select(ModelSnapshot))).scalars().all()
    assert (row.engine, row.host, row.model_name) == ("llamacpp", "http://gpu:8080", "hf.co/org/a-GGUF:a-Q4_K_M")


@pytest.mark.asyncio
async def test_an_unreachable_host_writes_nothing(monkeypatch, db):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _REAL_CLIENT(transport=httpx.MockTransport(refuse)))

    await LlamaCppPsPoller().poll_once()

    assert (await db.execute(select(ModelSnapshot))).scalars().all() == []
