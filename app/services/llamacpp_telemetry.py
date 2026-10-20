"""OpenTelemetry bootstrap for the Telemetry page's llama.cpp instrumentation (spans: llamacpp_client; storage:
telemetry_exporter, shared with Matricxon). Its own TracerProvider, never the process-global one, so tests can't
leak into each other (see matricxon_telemetry).
"""

import asyncio
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from app.config import INSTANCE_INDEX
from app.services.telemetry_exporter import DBSpanExporter, capture_main_loop

SCOPE = "pairing.llamacpp"
_SCHEDULE_DELAY_MILLIS = 2000
_NS_PER_MS = 1_000_000

logger = logging.getLogger("llama_chat")

_tracer_provider: TracerProvider | None = None


def init_llamacpp_telemetry() -> None:
    """Once per process from startup_service, on every instance: each routes its own calls."""
    global _tracer_provider
    capture_main_loop()
    resource = Resource.create({"service.name": "pairing", "service.instance.id": str(INSTANCE_INDEX)})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(DBSpanExporter(), schedule_delay_millis=_SCHEDULE_DELAY_MILLIS))
    _tracer_provider = provider
    logger.info("llama.cpp telemetry initialized (instance %d).", INSTANCE_INDEX)


def get_tracer() -> trace.Tracer:
    """Safe before init (e.g. in tests): the API's no-op tracer."""
    if _tracer_provider is not None:
        return _tracer_provider.get_tracer(SCOPE)
    return trace.get_tracer(SCOPE)


def record_chat_success(span: Span, host: str, attempts: int, timings: dict) -> None:
    """`timings` is llama-server's final-chunk object (prompt_n/prompt_ms/predicted_n/predicted_ms); empty if the
    stream closed first (e.g. a cancelled reply).
    """
    span.set_attribute("server.address", host)
    span.set_attribute("engine.attempt_count", attempts)
    if "prompt_n" in timings:
        span.set_attribute("gen_ai.usage.input_tokens", timings["prompt_n"])
    if "predicted_n" in timings:
        span.set_attribute("gen_ai.usage.output_tokens", timings["predicted_n"])
    prompt_ns = int(timings.get("prompt_ms", 0) * _NS_PER_MS)
    eval_ns = int(timings.get("predicted_ms", 0) * _NS_PER_MS)
    if "prompt_ms" in timings:
        span.set_attribute("engine.prompt_eval_duration_ns", prompt_ns)
    if "predicted_ms" in timings:
        span.set_attribute("engine.eval_duration_ns", eval_ns)
    if timings:
        span.set_attribute("engine.total_duration_ns", prompt_ns + eval_ns)


def record_chat_error(span: Span, host: str, attempts: int, exc: Exception) -> None:
    span.set_attribute("server.address", host)
    span.set_attribute("engine.attempt_count", attempts)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


async def shutdown_llamacpp_telemetry() -> None:
    """On a worker thread: shutting down on the loop's thread would deadlock with the exporter's final write."""
    if _tracer_provider is not None:
        await asyncio.to_thread(_tracer_provider.shutdown)
