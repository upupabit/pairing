"""GenerationParams.think (the chat's Reasoning chip, off by default): always sent, to Matricxon as `think` and to
llama.cpp as chat_template_kwargs.enable_thinking, so models that would reason on their own don't. Reasoning that
Matricxon returns in `message.thinking` stays out of the reply text."""

import httpx
import pytest

from app.schemas import GenerationParams
from app.services import llamacpp_client, matricxon_client, matricxon_pool


def _params(**overrides) -> dict:
    return GenerationParams(**overrides).model_dump()


def test_reasoning_is_off_by_default() -> None:
    assert GenerationParams().think is False


@pytest.mark.parametrize(("think", "sent"), [(True, True), (False, False), (None, False)])
def test_llamacpp_always_gets_the_template_switch(think: bool | None, sent: bool) -> None:
    payload = llamacpp_client._chat_payload("m", [], _params(think=think))
    assert payload["chat_template_kwargs"] == {"enable_thinking": sent}


@pytest.mark.asyncio
async def test_matricxon_gets_think_and_its_reasoning_is_left_out(monkeypatch) -> None:
    sent: list[dict] = []

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
            yield '{"message": {"content": "", "thinking": "Two plus two."}, "done": false}'
            yield '{"message": {"content": "It is 4."}, "done": false}'
            yield '{"done": true}'

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def stream(self, _method, _url, json):
            sent.append(json)
            return _Reply()

    monkeypatch.setattr(matricxon_pool, "stream_with_failover", on_one_host)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())

    on = [c async for c in matricxon_client.chat_stream("qwen", [], _params(think=True))]
    _ = [c async for c in matricxon_client.chat_stream("qwen", [], _params())]

    assert on == ["It is 4."]
    assert sent[0]["think"] is True and sent[1]["think"] is False
