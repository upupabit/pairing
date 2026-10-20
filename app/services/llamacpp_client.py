"""Async client for llama-server's router (OpenAI-style API): chat, embeddings, model list, unload. Every chat and
embedding call is an OpenTelemetry span for the Telemetry page (llamacpp_telemetry).

Models are addressed by their router name (llamacpp_models.LlamaCppModelName). A thinking model's reasoning
arrives separately in `delta.reasoning_content` (llama-server's default `--reasoning-format auto`) and is left out.
llama-server docs: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
"""

import json
import logging
from collections.abc import AsyncGenerator, Callable

import httpx
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.services import llamacpp_admin, llamacpp_pool, llamacpp_telemetry
from app.services.llamacpp_errors import LlamaCppError
from app.services.llamacpp_messages import OpenAIMessages, ToolCallCollector
from app.services.llamacpp_models import LlamaCppCatalog, LlamaCppModelName
from app.services.tool_call_sink import add_tools_to_payload, sink_from

__all__ = ["LlamaCppError", "chat_once", "chat_stream", "embed", "list_models", "stop_model"]

logger = logging.getLogger("llama_chat")

_REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
_CHAT_TIMEOUT = httpx.Timeout(None, connect=5.0)  # unbounded; reply_generation_service owns the reply timeout
_EMBED_MAX_ATTEMPTS = 2  # one retry, for a model still loading on its first request


def _router_name(model: str) -> str:
    """The local router knows pAIring's tags by LlamaCppModelName; a remote one by its own ids, used as listed."""
    return LlamaCppModelName.to_router(model) if llamacpp_pool.is_local() else model


def _error_detail(body: bytes, status_code: int) -> str:
    """llama-server's `{"error": {"message": ...}}`, else the raw text."""
    try:
        error = json.loads(body).get("error")
        detail = error.get("message") if isinstance(error, dict) else error
    except (ValueError, AttributeError):
        detail = None
    return detail or body.decode(errors="replace").strip() or f"llama-server returned HTTP {status_code}."


async def list_models() -> list[dict]:
    """Installed models. Local: the shared store, with capabilities from each file. Remote: the router's list,
    where only vision is known (tools are then tried, see tool_loop_service).
    """
    if llamacpp_pool.is_local():
        models = LlamaCppCatalog(await llamacpp_admin.store()).list_models()
        # The listed models are the ones a user can pick, so the router must know them too.
        await llamacpp_admin.sync_preset()
        return models
    host = llamacpp_pool.pick_host()
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        try:
            resp = await client.get(f"{host}/models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LlamaCppError(f"Could not reach llama-server at {host}: {exc}") from exc
    models = []
    for entry in resp.json().get("data", []):
        modalities = (entry.get("architecture") or {}).get("input_modalities") or []
        capabilities = ["completion", "vision"] if "image" in modalities else ["completion"]
        models.append({"name": entry["id"], "model": entry["id"], "capabilities": capabilities, "details": {}})
    return models


async def embed(text: str, model: str) -> list[float]:
    """Embeds `text` with `model`; retries the same host once (a cold load), then marks it failed."""
    host = llamacpp_pool.pick_host()
    last_error: Exception | None = None
    with llamacpp_telemetry.get_tracer().start_as_current_span(
        "llamacpp.embed", kind=SpanKind.CLIENT, record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("server.address", host)
        async with llamacpp_pool.track_request(host):
            for attempt in range(1, _EMBED_MAX_ATTEMPTS + 1):
                try:
                    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                        resp = await client.post(
                            f"{host}/v1/embeddings", json={"model": _router_name(model), "input": text}
                        )
                    if resp.is_error:
                        raise LlamaCppError(_error_detail(resp.content, resp.status_code))
                    llamacpp_pool.mark_recovered(host)
                    span.set_attribute("engine.attempt_count", attempt)
                    return resp.json()["data"][0]["embedding"]
                except (httpx.HTTPError, LlamaCppError) as exc:
                    last_error = exc
                    if attempt == 1 and isinstance(exc, LlamaCppError):
                        await llamacpp_admin.reload_if_unknown(str(exc))
                    logger.warning("Embedding request failed (attempt %d/%d): %s", attempt, _EMBED_MAX_ATTEMPTS, exc)
            llamacpp_pool.mark_failure(host)
            span.set_attribute("engine.attempt_count", _EMBED_MAX_ATTEMPTS)
            span.set_status(Status(StatusCode.ERROR, str(last_error)))
    raise LlamaCppError(f"Embedding request failed: {last_error}") from last_error


def _chat_payload(model: str, messages: list[dict], params: dict) -> dict:
    """Sampling fields llama-server accepts on /v1/chat/completions. `num_ctx` isn't per request: the preset sets it
    (llamacpp_preset), from the same system-wide Context window setting.
    """
    payload = {
        "model": _router_name(model),
        "messages": OpenAIMessages.convert(messages),
        "stream": True,
        "temperature": params["temperature"],
        "top_p": params["top_p"],
        "top_k": params["top_k"],
        "repeat_penalty": params["repeat_penalty"],
    }
    if params.get("num_predict", -1) not in (-1, None):
        payload["max_tokens"] = params["num_predict"]
    if params.get("seed", -1) != -1:
        payload["seed"] = params["seed"]
    add_tools_to_payload(payload, params)
    return payload


async def chat_stream(model: str, messages: list[dict], params: dict) -> AsyncGenerator[str, None]:
    """Streams a reply as text chunks. `messages` are oldest-first role/content dicts; `params` is
    GenerationParams-shaped. Tool calls go to params' ToolCallSink once the stream ends.
    """
    payload = _chat_payload(model, messages, params)
    sink = sink_from(params)
    call_state: dict = {"attempts": 0, "timings": {}}

    async def _chunks_from(host: str) -> AsyncGenerator[str, None]:
        # No try/except: stream_with_failover decides whether retrying another host is safe.
        call_state["host"] = host
        call_state["attempts"] += 1
        collector = ToolCallCollector()
        async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT) as client:
            async with client.stream("POST", f"{host}/v1/chat/completions", json=payload) as resp:
                if resp.is_error:
                    raise LlamaCppError(_error_detail(await resp.aread(), resp.status_code))
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        raise LlamaCppError(_error_detail(data.encode(), 500))
                    if event.get("timings"):
                        call_state["timings"] = event["timings"]
                    delta = ((event.get("choices") or [{}])[0]).get("delta") or {}
                    if delta.get("tool_calls"):
                        collector.add(delta["tool_calls"])
                    if delta.get("content"):
                        yield delta["content"]
        if sink:
            sink.add_calls(collector.calls())

    with llamacpp_telemetry.get_tracer().start_as_current_span(
        "llamacpp.chat", kind=SpanKind.CLIENT, record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("gen_ai.request.model", model)
        try:
            async for chunk in _stream_with_one_reload(_chunks_from):
                yield chunk
        except (httpx.HTTPError, LlamaCppError) as exc:
            llamacpp_telemetry.record_chat_error(span, call_state.get("host", ""), call_state["attempts"], exc)
            if isinstance(exc, LlamaCppError):
                raise
            raise LlamaCppError(f"Chat request failed: {exc}") from exc
        else:
            llamacpp_telemetry.record_chat_success(
                span, call_state.get("host", ""), call_state["attempts"], call_state["timings"]
            )


async def _stream_with_one_reload(
    chunks_from: Callable[[str], AsyncGenerator[str, None]],
) -> AsyncGenerator[str, None]:
    """Retries once after rebuilding the router's model list when it doesn't know the model (reload_if_unknown).
    That error comes before any text, so nothing is sent twice.
    """
    try:
        async for chunk in llamacpp_pool.stream_with_failover(chunks_from):
            yield chunk
    except LlamaCppError as exc:
        if not await llamacpp_admin.reload_if_unknown(str(exc)):
            raise
        async for chunk in llamacpp_pool.stream_with_failover(chunks_from):
            yield chunk


async def chat_once(model: str, messages: list[dict], params: dict | None = None) -> str:
    """Non-streaming helper for one-off internal calls (e.g. chat titles)."""
    params = params or {"temperature": 0.3, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_predict": 32}
    return "".join([chunk async for chunk in chat_stream(model, messages, params)])


async def stop_model(model: str) -> None:
    """Unloads `model` on every host (`POST /models/unload`), after a reply timed out or was cancelled. Best effort:
    a no-op where it isn't loaded, and failures are swallowed so cleanup never hides the real reason.
    """
    for host in llamacpp_pool.get_effective_hosts():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
                await client.post(f"{host}/models/unload", json={"model": _router_name(model)})
        except httpx.HTTPError:
            pass
