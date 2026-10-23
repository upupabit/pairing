"""Stats > Workflow analysis: the live view's recent history (services/workflow_history.py) and its report
(services/workflow_analysis.py)."""

from pydantic import BaseModel


class NodeBucket(BaseModel):
    """One Matricxon node over one history bucket. Sums over polls: divide by `polls` for an average."""

    polls: int = 0
    down: int = 0  # polls it could not be read
    reason: str | None = None  # the last read error
    running: int = 0
    queued: int = 0  # replies waiting for a free model slot
    decode: int = 0  # decode samples, and among them:
    slow: int = 0  # at least 1.5x below this node's usual speed
    ratio_sum: float = 0.0  # usual / current speed
    tps_by_model: dict[str, list[float]] = {}  # model -> [sum of tok/s, samples]
    # Polls where a reply was reading a long prompt from the start (workflow_history.LONG_READ_TOKENS),
    # and what it did to the node's other replies meanwhile.
    long_read: int = 0
    held_polls: int = 0  # ... while another reply waited for a slot or wrote slower than usual
    queued_in_read: int = 0
    slow_in_read: int = 0
    read_tokens: int = 0  # the longest such read: its new tokens, cached tokens and model
    read_reused: int = 0
    read_model: str | None = None
    # Stress, judged without a usual speed (a node that just started has none).
    crawl: int = 0  # decode samples below workflow_history.CRAWL_TPS
    min_tps: float | None = None
    long_wait: int = 0  # polls where a reply had waited LONG_WAIT_SECONDS or more without a first word
    max_wait: float = 0.0  # the longest such wait (s), from when the reply reached Matricxon


class FinishedReply(BaseModel):
    key: str  # host + request id, so a reply is counted once
    host: str
    model: str
    first_token_seconds: float | None = None
    tokens_per_second: float | None = None
    usual_tokens_per_second: float | None = None
    load_seconds: float | None = None
    started_at: float = 0.0  # wall-clock seconds the reply started (when it waited for a load)
    prompt_tokens: int = 0
    reused_tokens: int = 0


class HistoryBucket(BaseModel):
    start: float  # wall-clock seconds, so a saved history stays valid across restarts
    first_poll: float
    last_poll: float
    polls: int = 0
    nodes: dict[str, NodeBucket] = {}
    finished: list[FinishedReply] = []
    run_ids: list[str] = []  # this instance's chats finished in this bucket
    steps: dict[str, list[float]] = {}  # pAIring step -> durations (ms) of finished chats
    step_usual_ms: dict[str, float] = {}


class Finding(BaseModel):
    level: str  # "crit", "warn" or "info"
    title: str
    detail: str
    subject: str | None = None  # a node, model or step


class NodeRow(BaseModel):
    host: str
    seen_seconds: float
    down_share: float
    running: float  # average replies at once
    queued_share: float
    tokens_per_second: float | None = None
    slow_share: float
    slowness: float | None = None  # average usual / current speed while writing


class ModelRow(BaseModel):
    model: str
    replies: int
    first_token_seconds: float | None = None
    tokens_per_second: float | None = None
    waited: int = 0  # replies that waited for a load
    loads: int = 0  # times the model was loaded (replies waiting for the same load count once)
    load_seconds: float = 0.0  # time replies spent waiting, together
    reuse_share: float | None = None  # prompt tokens reused from the cache


class StepRow(BaseModel):
    step: str
    runs: int
    median_ms: float
    p90_ms: float
    usual_ms: float | None = None


class WorkflowAnalysis(BaseModel):
    window_seconds: float
    covered_seconds: float  # time within the window the live view or this page was open
    polls: int
    nodes_seen: int
    replies_finished: int
    findings: list[Finding] = []
    nodes: list[NodeRow] = []  # the ones worth a look first
    nodes_more: int = 0
    models: list[ModelRow] = []
    steps: list[StepRow] = []
