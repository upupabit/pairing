"""Tests for services/llamacpp_client.py against a mock llama-server (httpx.MockTransport). Stream shapes are
copied from a real llama-server b11443 run: reasoning in `reasoning_content`, tool calls as fragments, `timings`
on the last chunk.
"""

import json

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.schemas import LlamaCppServerConfig
from app.services import llamacpp_admin, llamacpp_client, llamacpp_pool, llamacpp_telemetry
from app.services.llamacpp_errors import LlamaCppError
from app.services.tool_call_sink import ToolCallSink

_PARAMS = {"temperature": 0.5, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_ctx": 4096, "num_predict": 64}
_TAG = "hf.co/org/chat-GGUF:chat-Q4_K_M"
_REAL_CLIENT = httpx.AsyncClient


def _sse(*events: dict) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events) + b"data: [DONE]\n\n"


def _delta(**delta) -> dict:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


@pytest.fixture
def server(monkeypatch):
    """Routes every httpx.AsyncClient to a handler; `server.requests` records (method, path, json body)."""

    class Server:
        requests: list[tuple[str, str, dict | None]] = []
        queue: list[httpx.Response] = []
        reply: httpx.Response = httpx.Response(200, json={})

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        Server.requests.append((request.method, request.url.path, body))
        return Server.queue.pop(0) if Server.queue else Server.reply

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), timeout=kw.get("timeout")),
    )
    Server.requests = []
    Server.queue = []
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())
    yield Server
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(llamacpp_telemetry, "_tracer_provider", provider)
    return exporter


async def _collect(params: dict | None = None, messages: list[dict] | None = None) -> str:
    chunks = llamacpp_client.chat_stream(_TAG, messages or [{"role": "user", "content": "hi"}], params or _PARAMS)
    return "".join([c async for c in chunks])


@pytest.mark.asyncio
async def test_chat_stream_yields_content_and_leaves_reasoning_out(server, spans):
    timings = {"prompt_n": 15, "prompt_ms": 500.0, "predicted_n": 3, "predicted_ms": 300.0}
    server.reply = httpx.Response(
        200,
        content=_sse(
            _delta(reasoning_content="thinking..."),
            _delta(content="Hi "),
            _delta(content="there"),
            {
                "choices": [],
                "timings": timings,
            },
        ),
    )

    assert await _collect() == "Hi there"

    method, path, body = server.requests[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert body["model"] == "hf.co/org/chat-GGUF@chat-Q4_K_M"
    assert body["max_tokens"] == 64 and body["top_k"] == 40 and "seed" not in body
    [span] = spans.get_finished_spans()
    assert span.attributes["gen_ai.usage.input_tokens"] == 15
    assert span.attributes["engine.eval_duration_ns"] == 300_000_000
    assert span.attributes["engine.total_duration_ns"] == 800_000_000


@pytest.mark.asyncio
async def test_chat_stream_joins_tool_call_fragments_into_the_sink(server):
    server.reply = httpx.Response(
        200,
        content=_sse(
            _delta(
                tool_calls=[
                    {"index": 0, "id": "c1", "type": "function", "function": {"name": "weather", "arguments": "{"}}
                ]
            ),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": '"city": "Paris"}'}}]),
        ),
    )
    sink = ToolCallSink()

    assert await _collect({**_PARAMS, "tools": [{"type": "function"}], "tool_sink": sink}) == ""

    assert sink.take() == [{"id": "c1", "function": {"name": "weather", "arguments": {"city": "Paris"}}}]
    assert server.requests[0][2]["tools"] == [{"type": "function"}]


@pytest.mark.asyncio
async def test_chat_stream_sends_images_as_content_parts(server):
    server.reply = httpx.Response(200, content=_sse(_delta(content="a cat")))

    await _collect(messages=[{"role": "user", "content": "what?", "images": ["iVBORw0KGgo="]}])

    [message] = server.requests[0][2]["messages"]
    assert message["content"] == [
        {"type": "text", "text": "what?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
    ]


@pytest.fixture
def reloads(monkeypatch):
    """Stubs the preset rebuild (it would read the real database) and counts calls."""
    calls: list[int] = []

    async def fake_sync(reload: bool = True) -> None:
        calls.append(1)

    monkeypatch.setattr(llamacpp_admin, "sync_preset", fake_sync)
    return calls


@pytest.mark.asyncio
async def test_chat_stream_surfaces_the_servers_error_message(server, spans, reloads):
    server.reply = httpx.Response(400, json={"error": {"code": 400, "message": "model is not found"}})

    with pytest.raises(LlamaCppError, match="model is not found"):
        await _collect()

    [span] = spans.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_embed_posts_to_the_openai_endpoint(server):
    server.reply = httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    assert await llamacpp_client.embed("hello", "hf.co/org/emb-GGUF:Q8_0") == [0.1, 0.2]
    assert server.requests[0] == ("POST", "/v1/embeddings", {"model": "hf.co/org/emb-GGUF@Q8_0", "input": "hello"})


@pytest.mark.asyncio
async def test_embed_retries_once_then_raises(server):
    server.reply = httpx.Response(503, json={"error": {"message": "loading model"}})

    with pytest.raises(LlamaCppError, match="loading model"):
        await llamacpp_client.embed("hello", _TAG)
    assert len(server.requests) == 2


@pytest.mark.asyncio
async def test_stop_model_unloads_it_and_never_raises(server):
    server.reply = httpx.Response(400, json={"error": {"message": "model is not loaded"}})

    await llamacpp_client.stop_model(_TAG)

    assert server.requests == [("POST", "/models/unload", {"model": "hf.co/org/chat-GGUF@chat-Q4_K_M"})]


@pytest.mark.asyncio
async def test_remote_list_uses_the_routers_ids_as_they_are(server):
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig(mode="remote", remote_hosts=["http://gpu:8080"]))
    server.reply = httpx.Response(
        200, json={"data": [{"id": "org/vlm:Q4_K_M", "architecture": {"input_modalities": ["text", "image"]}}]}
    )

    [model] = await llamacpp_client.list_models()

    assert model["name"] == "org/vlm:Q4_K_M"
    assert model["capabilities"] == ["completion", "vision"]


@pytest.mark.asyncio
async def test_an_unknown_model_rebuilds_the_model_list_and_retries_once(server, reloads):
    """A model Matricxon pulled into the shared folder isn't in the router's preset until it is rebuilt."""
    server.queue = [
        httpx.Response(400, json={"error": {"message": "model 'hf.co/org/chat-GGUF@chat-Q4_K_M' not found"}}),
        httpx.Response(200, content=_sse(_delta(content="ok"))),
    ]

    assert await _collect() == "ok"
    assert len(reloads) == 1 and len(server.requests) == 2


@pytest.mark.asyncio
async def test_an_unknown_model_still_missing_after_the_rebuild_is_reported(server, reloads):
    server.reply = httpx.Response(400, json={"error": {"message": "model 'x' not found"}})

    with pytest.raises(LlamaCppError, match="not found"):
        await _collect()
    assert len(reloads) == 1 and len(server.requests) == 2


@pytest.mark.asyncio
async def test_other_errors_are_not_retried(server, reloads):
    server.reply = httpx.Response(500, json={"error": {"message": "out of memory"}})

    with pytest.raises(LlamaCppError, match="out of memory"):
        await _collect()
    assert reloads == [] and len(server.requests) == 1


@pytest.mark.asyncio
async def test_listing_local_models_keeps_the_router_in_step(server, reloads, monkeypatch, tmp_path):
    from app.services.gguf_model_store import GgufModelStore

    async def fake_store():
        return GgufModelStore(tmp_path)

    monkeypatch.setattr(llamacpp_admin, "store", fake_store)

    assert await llamacpp_client.list_models() == []
    assert reloads == [1]
