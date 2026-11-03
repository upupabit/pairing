"""A reply's speed (services/reply_stats.py) and the engines' usage chunks."""

import pytest
from sqlalchemy import select

from app.models import Conversation, Message
from app.services import reply_cross_instance_service, reply_generation_service, reply_model_unload_service
from app.services.reply_stats import ReplyStats
from tests.test_reply_generation_service import _build_session_factory, _drain_background_tasks, _make_conversation


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_times_and_engine_token_counts():
    clock = _Clock()
    stats = ReplyStats(clock)
    clock.now = 100.5
    stats.text()
    clock.now = 101.0
    stats.text()  # only the first text counts
    stats.usage(ReplyStats.from_llamacpp({"predicted_n": 40, "predicted_ms": 2000, "prompt_n": 12}))
    clock.now = 103.0

    assert stats.result() == {
        "first_token_ms": 500,
        "total_ms": 3000,
        "output_tokens": 40,
        "prompt_tokens": 12,
        "tokens_per_second": 20.0,
    }


def test_a_tool_loop_adds_up_and_falls_back_to_measured_time():
    clock = _Clock()
    stats = ReplyStats(clock)
    stats.text()
    stats.usage({"output_tokens": 10})
    stats.usage({"output_tokens": 30})
    clock.now = 102.0

    result = stats.result()
    assert result["output_tokens"] == 40 and result["tokens_per_second"] == 20.0


def test_matricxon_done_line_and_no_counts_from_a_connector():
    done = {
        "eval_count": 8,
        "eval_duration": 1_400_000_000,
        "prompt_eval_duration": 1_000_000_000,
        "prompt_eval_count": 3,
    }
    assert ReplyStats.from_matricxon(done) == {
        "output_tokens": 8,
        "output_ms": 400.0,
        "prompt_tokens": 3,
    }
    clock = _Clock()
    stats = ReplyStats(clock)
    assert stats.result() is None  # no text, nothing to time
    stats.text()
    assert set(stats.result()) == {"first_token_ms", "total_ms"}


@pytest.mark.asyncio
async def test_a_finished_reply_keeps_its_stats_and_sends_them_with_done(monkeypatch):
    engine, session_factory = await _build_session_factory()
    for module in (reply_generation_service, reply_model_unload_service, reply_cross_instance_service):
        monkeypatch.setattr(module, "AsyncSessionLocal", session_factory)
    conversation_id = await _make_conversation(session_factory)
    seen_params = []

    async def engine_stream(_model, _messages, params):
        seen_params.append(params)
        yield "Hello"
        yield {"usage": {"output_tokens": 5, "output_ms": 250, "prompt_tokens": 9}}

    monkeypatch.setattr(reply_generation_service, "chat_stream", engine_stream)
    try:
        async with session_factory() as db:
            conversation = await db.get(Conversation, conversation_id)
            events = [e async for e in reply_generation_service.stream_reply(db, conversation, [], [])]
        await _drain_background_tasks()
        async with session_factory() as db:
            reply = (await db.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
        assert seen_params[0]["usage_events"] is True
        assert reply.content == "Hello" and reply.stats["tokens_per_second"] == 20.0
        assert events[-1]["done"] and events[-1]["stats"]["output_tokens"] == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_matricxon_sends_usage_only_to_callers_that_ask(monkeypatch):
    import httpx

    from app.services import matricxon_client, matricxon_pool

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
            yield '{"message": {"content": "Hi!"}, "done": false}'
            yield '{"done": true, "eval_count": 4, "eval_duration": 200000000, "prompt_eval_count": 2}'

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
    asked = [c async for c in matricxon_client.chat_stream("m", [], {**params, "usage_events": True})]

    assert plain == ["Hi!"]
    assert asked == ["Hi!", {"usage": {"output_tokens": 4, "output_ms": 200.0, "prompt_tokens": 2}}]
