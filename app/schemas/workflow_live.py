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
    # The same, split at the first token: reading the prompt, then writing the reply (older Matricxon: empty).
    prefill_stage_seconds: dict[str, float] = {}
    decode_stage_seconds: dict[str, float] = {}
    stage_timing: bool = False
    usual_tokens_per_second: float | None = None
    usual_prefill_tokens_per_second: float | None = None


class EngineCrowd(BaseModel):
    replies: int = 0
    tokens_per_second: float = 0.0  # combined


class LiveCrowd(BaseModel):
    """Chats not sent in full on a large cluster (services/workflow_live_summary.py), as counts."""

    running: int = 0
    busy_nodes: int = 0  # Matricxon nodes with a running reply, counting the chats sent in full
    engine: dict[str, EngineCrowd] = {}  # by phase
    app: dict[str, int] = {}  # running chats per pAIring step


class WorkflowLiveSnapshot(BaseModel):
    engine: str
    live: bool  # False unless the active engine is Matricxon
    runs: list[LiveRunView] = []
    usual_ms: dict[str, float] = {}
    engine_requests: list[EngineRequestView] = []
    engine_node_count: int = 0  # Matricxon hosts polled (more than one: a cluster)
    engine_error: str | None = None
    crowd: LiveCrowd | None = None  # None: every chat is in runs/engine_requests
