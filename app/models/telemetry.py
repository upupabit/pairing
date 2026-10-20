"""llama.cpp/Matricxon telemetry rows, written by an OpenTelemetry span exporter (app/services/llamacpp_telemetry.py,
matricxon_telemetry.py) and aggregated by telemetry_service.py, one engine at a time.

Both tables are append-only logs never looked up by id externally, so they use autoincrement integer keys
instead of new_id.

Column names follow Ollama's timing fields, the first engine's; `engine` identifies the source. Rows from before
the move to llama.cpp keep engine "ollama".
"""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, String, Text

from app.database import Base


class TelemetryEvent(Base):
    """One completed or failed llama.cpp/Matricxon call (chat_stream/embed), written by that engine's DBSpanExporter
    (telemetry_exporter.py) when its span ends. duration_ms is our wall-clock; the total_/load_/*_eval_*
    fields are the engine's own timing, only for "chat" events (embeddings carry none).
    """

    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # "llamacpp" | "matricxon": the engine that served this call, stamped from the span's instrumentation scope
    # (telemetry_exporter._persist_spans), so switching engines never rewrites history.
    engine = Column(String(20), nullable=False, default="llamacpp")
    kind = Column(String(20), nullable=False)
    model = Column(String(255), nullable=True)
    host = Column(String(255), nullable=False)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    duration_ms = Column(Float, nullable=False)
    total_duration_ms = Column(Float, nullable=True)
    load_duration_ms = Column(Float, nullable=True)
    prompt_eval_duration_ms = Column(Float, nullable=True)
    eval_duration_ms = Column(Float, nullable=True)
    prompt_eval_count = Column(Integer, nullable=True)
    eval_count = Column(Integer, nullable=True)
    # Hosts tried by chat_stream's failover (or embed's cold-start retries); 1 normally.
    attempt_count = Column(Integer, nullable=False, default=1)


class ModelSnapshot(Base):
    """One row per (host, loaded model) on each engine poll (llamacpp_ps_poller, matricxon_ps_poller).
    Appended, not upserted: small at a 30s interval, and a cheap time series. model_snapshot_service reads the
    newest row per (engine, host, model_name).
    """

    __tablename__ = "model_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # "llamacpp" | "matricxon" (see TelemetryEvent.engine).
    engine = Column(String(20), nullable=False, default="llamacpp")
    host = Column(String(255), nullable=False)
    model_name = Column(String(255), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    size_vram_bytes = Column(BigInteger, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    polled_at = Column(DateTime, nullable=False)
