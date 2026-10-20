"""Tests for services/llamacpp_telemetry.py: llama-server's `timings` become the span attributes the shared exporter
stores, and spans from its scope are stamped engine "llamacpp". Never touches the global OTel registry.
"""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.services import llamacpp_telemetry, telemetry_exporter


def _span(monkeypatch, timings: dict):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(llamacpp_telemetry, "_tracer_provider", provider)
    with llamacpp_telemetry.get_tracer().start_as_current_span("llamacpp.chat") as span:
        llamacpp_telemetry.record_chat_success(span, "http://127.0.0.1:8091", 1, timings)
    return exporter.get_finished_spans()[0]


def test_timings_map_to_token_counts_and_nanosecond_durations(monkeypatch):
    span = _span(monkeypatch, {"prompt_n": 10, "prompt_ms": 2.5, "predicted_n": 4, "predicted_ms": 7.5})

    assert span.attributes["gen_ai.usage.input_tokens"] == 10
    assert span.attributes["gen_ai.usage.output_tokens"] == 4
    assert span.attributes["engine.prompt_eval_duration_ns"] == 2_500_000
    assert span.attributes["engine.total_duration_ns"] == 10_000_000


def test_a_cancelled_reply_without_timings_records_no_durations(monkeypatch):
    span = _span(monkeypatch, {})

    assert "engine.total_duration_ns" not in span.attributes
    assert span.attributes["engine.attempt_count"] == 1


def test_the_exporter_stamps_spans_from_its_scope_as_llamacpp(monkeypatch):
    span = _span(monkeypatch, {"predicted_ms": 1.0})

    event = telemetry_exporter._span_to_event(span, telemetry_exporter._ENGINE_BY_SCOPE[llamacpp_telemetry.SCOPE])

    assert (event.engine, event.kind, event.eval_duration_ms) == ("llamacpp", "chat", 1.0)


def test_get_tracer_before_init_is_a_no_op_tracer(monkeypatch):
    monkeypatch.setattr(llamacpp_telemetry, "_tracer_provider", None)

    with llamacpp_telemetry.get_tracer().start_as_current_span("llamacpp.embed") as span:
        assert not span.is_recording()
