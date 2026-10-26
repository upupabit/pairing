"""Reasoning ticks (params["reasoning_ticks"]): while a model only reasons, the engine clients pass its text as
{"reasoning": text} (never reply text), so reply generation still runs its delete check: a reply deleted
through another instance during a long reasoning phase stops the engine instead of running on unwatched."""

import asyncio
import os

import httpx
import pytest

from app.models import Conversation, Message
from app.services import (
    inference_client,
    matricxon_client,
    matricxon_pool,
    reply_cross_instance_service,
    reply_generation_service,
    reply_model_unload_service,
    tool_loop_service,
)
from app.services.reply_side_events import ReplySideEvents
from tests.test_reply_generation_service import (
    _build_file_session_factory,
    _drain_background_tasks,
    _make_conversation,
)


@pytest.mark.asyncio
async def test_a_reply_deleted_elsewhere_while_only_reasoning_stops_the_engine(monkeypatch) -> None:
    engine, session_factory, db_path = await _build_file_session_factory()
    for module in (reply_generation_service, reply_model_unload_service, reply_cross_instance_service):
        monkeypatch.setattr(module, "AsyncSessionLocal", session_factory)
    conversation_id = await _make_conversation(session_factory)
    proceed, never, seen_params = asyncio.Event(), asyncio.Event(), []

    async def reasoning_only(_model, _messages, params):
        seen_params.append(params)
        await proceed.wait()
        await asyncio.sleep(ReplySideEvents.CHECK_SECONDS + 0.05)
        yield {"reasoning": "1. **Analyze:**\n"}
        await never.wait()
        yield "unreachable"  # pragma: no cover

    stopped: list[str | None] = []

    async def fake_stop_model(_model, request_id=None):
        stopped.append(request_id)

    monkeypatch.setattr(reply_generation_service, "chat_stream", reasoning_only)
    monkeypatch.setattr(reply_generation_service, "stop_model", fake_stop_model)
    try:
        async with session_factory() as db:
            conversation = await db.get(Conversation, conversation_id)
            gen = reply_generation_service.stream_reply(db, conversation, [{"role": "user", "content": "hi"}], [])
            message_id = (await gen.__anext__())["message_id"]
            other_instance = session_factory()
            message = await other_instance.get(Message, message_id)
            message.status = "deleted"
            await other_instance.commit()
            await other_instance.close()
            proceed.set()
            await gen.aclose()
        await _drain_background_tasks()
        assert stopped == [message_id]
        assert seen_params[0]["reasoning_ticks"] is True
    finally:
        await engine.dispose()
        os.remove(db_path)


@pytest.mark.asyncio
async def test_matricxon_sends_ticks_only_to_callers_that_ask(monkeypatch) -> None:
    async def on_one_host(make_stream, prefer=None, info=None, retry_on=()):
        async for chunk in make_stream("http://mx:8420"):
            yield chunk

    class _Reply:
        is_error = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def aiter_lines(self):
            yield '{"message": {"content": "", "thinking": "Hmm."}, "done": false}'
            yield '{"message": {"content": "Hi!"}, "done": false}'
            yield '{"done": true}'

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def stream(self, _method, _url, json):
            return _Reply()

    monkeypatch.setattr(matricxon_pool, "stream_with_failover", on_one_host)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())
    params = {"temperature": 0.8, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_ctx": 512, "num_predict": 9}

    plain = [c async for c in matricxon_client.chat_stream("m", [], params)]
    ticks = [c async for c in matricxon_client.chat_stream("m", [], {**params, "reasoning_ticks": True})]

    assert plain == ["Hi!"]
    assert ticks == [{"reasoning": "Hmm."}, "Hi!"]


@pytest.mark.asyncio
async def test_the_tool_loop_passes_ticks_on_without_adding_them_to_the_text(monkeypatch) -> None:
    async def engine(_model, _messages, _params):
        yield {"reasoning": "Hmm."}
        yield "Answer."

    monkeypatch.setattr(inference_client, "chat_stream", engine)
    loop = tool_loop_service.ToolLoop.__new__(tool_loop_service.ToolLoop)
    loop._max_rounds, loop._definitions = 0, []

    chunks = [c async for c in loop.run("m", [], {})]

    assert chunks == [{"reasoning": "Hmm."}, "Answer."]
