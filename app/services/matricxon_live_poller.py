"""Reads each Matricxon node's GET /api/live for the live workflow view, only while a Stats page watches
(workflow_live_service polls it). Several viewers share one short-lived cache. Each read also keeps Matricxon's
stage timing switched on for a short while (Matricxon's LiveRegistry.WATCH_SECONDS).

Also learns each model's usual decode and prefill rates from finished replies, so a slow one can be flagged.
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


async def _fetch_host(host: str) -> list[dict]:
    async with matricxon_http.client(timeout=2.0) as client:
        resp = await client.get(f"{host}/api/live")
        resp.raise_for_status()
    return resp.json().get("requests", [])


class MatricxonLivePoller:
    CACHE_SECONDS = 0.4
    SAMPLES = 20

    def __init__(
        self,
        fetch: Fetch = _fetch_host,
        hosts: Callable[[], list[str]] = matricxon_pool.get_effective_hosts,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._hosts = hosts
        self._clock = clock
        self._cached_at = float("-inf")
        self._cached: tuple[list[EngineRequestView], str | None] = ([], None)
        self._lock = asyncio.Lock()
        self._seen_done: set[str] = set()
        self._decode: dict[str, deque[float]] = {}
        self._prefill: dict[str, deque[float]] = {}

    async def requests(self) -> tuple[list[EngineRequestView], str | None]:
        """(replies on every node, an error text if a node could not be read)."""
        async with self._lock:
            if self._clock() - self._cached_at >= self.CACHE_SECONDS:
                self._cached = await self._poll()
                self._cached_at = self._clock()
            return self._cached

    async def _poll(self) -> tuple[list[EngineRequestView], str | None]:
        hosts = self._hosts()
        results = await asyncio.gather(*(self._fetch(host) for host in hosts), return_exceptions=True)
        views: list[EngineRequestView] = []
        errors: list[str] = []
        for host, result in zip(hosts, results, strict=True):
            if isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 404:
                errors.append(f"{host} has no live view yet (update Matricxon)")
            elif isinstance(result, Exception):
                errors.append(f"{host}: {result}")
            else:
                views.extend(self._view(host, raw) for raw in result)
        return views, "; ".join(errors) or None

    def _view(self, host: str, raw: dict) -> EngineRequestView:
        view = EngineRequestView(host=host, **raw)
        if view.phase == "done" and view.request_id not in self._seen_done:
            self._seen_done.add(view.request_id)
            self._learn(view)
        view.usual_tokens_per_second = self._median(self._decode.get(view.model))
        view.usual_prefill_tokens_per_second = self._median(self._prefill.get(view.model))
        return view

    def _learn(self, view: EngineRequestView) -> None:
        if len(self._seen_done) > 1000:
            self._seen_done.clear()
        if view.tokens_per_second:
            self._decode.setdefault(view.model, deque(maxlen=self.SAMPLES)).append(view.tokens_per_second)
        new_tokens = view.prompt_tokens - view.reused_tokens
        if view.first_token_seconds and new_tokens > 32:
            rate = new_tokens / view.first_token_seconds
            self._prefill.setdefault(view.model, deque(maxlen=self.SAMPLES)).append(rate)

    @staticmethod
    def _median(samples: deque[float] | None) -> float | None:
        return round(statistics.median(samples), 2) if samples and len(samples) >= 3 else None


matricxon_live_poller = MatricxonLivePoller()
