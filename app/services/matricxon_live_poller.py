"""Reads each Matricxon node's GET /api/live for the live workflow view, only while a Stats page watches
(workflow_live_service polls it). Several viewers share one short-lived cache. Each read also keeps Matricxon's
stage timing switched on for a short while (Matricxon's LiveRegistry.WATCH_SECONDS).

Polite on a large cluster: one shared HTTP client keeps connections open, at most CONCURRENCY reads run at once,
the cache lasts longer as the cluster grows, and a node that failed is left alone for RETRY_SECONDS.

Also learns each model's usual decode and prefill rates from finished replies, per node (a weaker node is not
"slow" against itself), so a slow one can be flagged.
"""

import asyncio
import statistics
import time
from collections import deque
from collections.abc import Awaitable, Callable

import httpx

from app.schemas.workflow_live import EngineRequestView
from app.services import matricxon_http, matricxon_pool

Fetch = Callable[[str], Awaitable[list[dict]]]


class _LiveReader:
    """Reads one node's GET /api/live through a client kept open between polls."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __call__(self, host: str) -> list[dict]:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_connections=MatricxonLivePoller.CONCURRENCY, keepalive_expiry=30)
            self._client = matricxon_http.client(timeout=2.0, limits=limits)
        resp = await self._client.get(f"{host}/api/live")
        resp.raise_for_status()
        return resp.json().get("requests", [])


class MatricxonLivePoller:
    CACHE_SECONDS = 0.4  # up to 200 nodes; longer above (0.002 s per node: 2 s at 1000)
    CONCURRENCY = 50
    RETRY_SECONDS = 10.0
    SAMPLES = 20
    ERRORS_SHOWN = 3

    def __init__(
        self,
        fetch: Fetch | None = None,
        hosts: Callable[[], list[str]] = matricxon_pool.get_effective_hosts,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch or _LiveReader()
        self._gate = asyncio.Semaphore(self.CONCURRENCY)
        self._failed: dict[str, tuple[float, str]] = {}  # host -> (retry at, error text)
        self._hosts = hosts
        self._clock = clock
        self._cached_at = float("-inf")
        self._cached: tuple[list[EngineRequestView], str | None] = ([], None)
        self._lock = asyncio.Lock()
        self._seen_done: set[str] = set()
        self._decode: dict[str, deque[float]] = {}
        self._prefill: dict[str, deque[float]] = {}
        self.nodes: list[str] = []  # the hosts last polled
        self.unreachable: dict[str, str] = {}  # host -> error, as of the last poll
        self.polled_at = float("-inf")

    async def requests(self) -> tuple[list[EngineRequestView], str | None]:
        """(replies on every node, an error text if a node could not be read)."""
        async with self._lock:
            if self._clock() - self._cached_at >= max(self.CACHE_SECONDS, 0.002 * len(self.nodes)):
                self._cached = await self._poll()
                self._cached_at = self.polled_at = self._clock()
            return self._cached

    async def _poll(self) -> tuple[list[EngineRequestView], str | None]:
        self.nodes = self._hosts()
        now = self._clock()
        resting = {h for h in self.nodes if self._failed.get(h, (0.0, ""))[0] > now}
        hosts = [h for h in self.nodes if h not in resting]
        results = await asyncio.gather(*(self._read(host) for host in hosts), return_exceptions=True)
        views: list[EngineRequestView] = []
        errors = [self._failed[h][1] for h in self.nodes if h in resting]
        for host, result in zip(hosts, results, strict=True):
            if isinstance(result, Exception):
                errors.append(self._error_text(host, result))
                self._failed[host] = (now + self.RETRY_SECONDS, errors[-1])
            else:
                self._failed.pop(host, None)
                views.extend(self._view(host, raw) for raw in result)
        self.unreachable = {h: self._failed[h][1] for h in self.nodes if h in self._failed}
        if len(errors) > self.ERRORS_SHOWN:  # a large cluster: name a few, count the rest
            errors = [*errors[: self.ERRORS_SHOWN], f"and {len(errors) - self.ERRORS_SHOWN} more nodes"]
        return self._latest_attempts(views), "; ".join(errors) or None

    async def _read(self, host: str) -> list[dict]:
        async with self._gate:
            return await self._fetch(host)

    @staticmethod
    def _error_text(host: str, error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 404:
            return f"{host} has no live view yet (update Matricxon)"
        return f"{host}: {error}"

    @staticmethod
    def _latest_attempts(views: list[EngineRequestView]) -> list[EngineRequestView]:
        """One view per reply. After a failover two nodes report the same id for a while: keep the running attempt,
        else the newest."""
        best: dict[str, EngineRequestView] = {}
        for view in views:
            kept = best.get(view.request_id)
            if kept is None or (kept.phase == "done", kept.elapsed_seconds) > (
                view.phase == "done",
                view.elapsed_seconds,
            ):
                best[view.request_id] = view
        return list(best.values())

    def _view(self, host: str, raw: dict) -> EngineRequestView:
        view = EngineRequestView(host=host, **raw)
        if view.phase == "done" and f"{host} {view.request_id}" not in self._seen_done:
            self._seen_done.add(f"{host} {view.request_id}")
            self._learn(view)
        key = f"{host} {view.model}"
        view.usual_tokens_per_second = self._median(self._decode.get(key))
        view.usual_prefill_tokens_per_second = self._median(self._prefill.get(key))
        return view

    def _learn(self, view: EngineRequestView) -> None:
        if len(self._seen_done) > 1000:
            self._seen_done.clear()
        key = f"{view.host} {view.model}"
        if view.tokens_per_second:
            self._decode.setdefault(key, deque(maxlen=self.SAMPLES)).append(view.tokens_per_second)
        new_tokens = view.prompt_tokens - view.reused_tokens
        if view.first_token_seconds and new_tokens > 32:
            rate = new_tokens / view.first_token_seconds
            self._prefill.setdefault(key, deque(maxlen=self.SAMPLES)).append(rate)

    @staticmethod
    def _median(samples: deque[float] | None) -> float | None:
        return round(statistics.median(samples), 2) if samples and len(samples) >= 3 else None


matricxon_live_poller = MatricxonLivePoller()
