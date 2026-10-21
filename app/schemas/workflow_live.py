"""Stats > Visual chat workflow live view (services/workflow_live_service.py)."""

from pydantic import BaseModel


class LiveNodeTiming(BaseModel):
    active: bool
    elapsed_ms: float  # total time in this node so far (including a running stretch)
    count: int


class LiveRunView(BaseModel):
    run_id: str
    request_id: str | None = None
    model: str
    elapsed_ms: float
    done: bool
    chunks: int
    nodes: dict[str, LiveNodeTiming]


class EngineRequestView(BaseModel):
    """One reply on a Matricxon node (its GET /api/live), plus recent usual rates for its model."""

    host: str
    request_id: str
    model: str
    phase: str
    elapsed_seconds: float
    load_seconds: float | None = None
    prompt_tokens: int = 0
    reused_tokens: int = 0
    prefilled_tokens: int = 0
    generated_tokens: int = 0
    first_token_seconds: float | None = None
    tokens_per_second: float | None = None
    layer: int | None = None
    layer_count: int | None = None
    stage_seconds: dict[str, float] = {}
    stage_timing: bool = False
    usual_tokens_per_second: float | None = None
    usual_prefill_tokens_per_second: float | None = None


class WorkflowLiveSnapshot(BaseModel):
    engine: str
    live: bool  # False unless the active engine is Matricxon
    runs: list[LiveRunView] = []
    usual_ms: dict[str, float] = {}
    engine_requests: list[EngineRequestView] = []
    engine_error: str | None = None
