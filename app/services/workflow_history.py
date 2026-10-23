"""The live workflow view's recent history, for Stats > Workflow analysis (workflow_analysis.py).

Filled only while someone watches (the live view or the analysis page), from the full data before it is summarised
for the browser. Kept small: 10-second buckets over the last WINDOW_SECONDS, sums instead of samples, capped lists.
Saved to DATA_DIR every SAVE_SECONDS (longer past 1 MB), so a restart keeps the last minutes; anything older is
dropped on load.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from app.config import DATA_DIR
from app.schemas.workflow_analysis import FinishedReply, HistoryBucket, NodeBucket
from app.schemas.workflow_live import EngineRequestView, LiveRunView

logger = logging.getLogger(__name__)

SLOW_RATIO = 1.5
# A reply reading at least this many new prompt tokens (not from the cache) can hold a slow node up.
LONG_READ_TOKENS = 1000
# Absolute signs of an overloaded node: writing slower than this, or no first word after this long.
CRAWL_TPS = 1.0
LONG_WAIT_SECONDS = 60.0
WAITING_PHASES = ("loading", "building", "queued", "prefill")


class WorkflowHistory:
    WINDOW_SECONDS = 300.0
    BUCKET_SECONDS = 10.0
    SAVE_SECONDS = 5.0
    MAX_FINISHED = 500  # per bucket
    MAX_DURATIONS = 200  # per step and bucket

    def __init__(self, path: Path = DATA_DIR / "workflow_history.json", clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._buckets: list[HistoryBucket] | None = None  # loaded on first use
        self._seen: set[str] = set()
        self._saved_at = 0.0
        self._save_every = self.SAVE_SECONDS
        self._dirty = False

    def buckets(self) -> list[HistoryBucket]:
        """The buckets still inside the window, oldest first."""
        self._load()
        cutoff = self._clock() - self.WINDOW_SECONDS
        if self._buckets and self._buckets[0].start + self.BUCKET_SECONDS < cutoff:
            self._buckets = [b for b in self._buckets if b.start + self.BUCKET_SECONDS >= cutoff]
            self._seen = self._keys(self._buckets)
        return self._buckets

    def record(
        self,
        hosts: list[str],
        unreachable: dict[str, str],
        requests: list[EngineRequestView],
        runs: list[LiveRunView],
        step_usual_ms: dict[str, float],
    ) -> None:
        """One poll of every node, plus this instance's chats."""
        bucket = self._bucket()
        bucket.polls += 1
        bucket.step_usual_ms = step_usual_ms
        for host in hosts:
            node = bucket.nodes.setdefault(host, NodeBucket())
            node.polls += 1
            if host in unreachable:
                node.down += 1
                node.reason = unreachable[host]
        reads = self._long_reads(requests)
        for request in requests:
            node = bucket.nodes.setdefault(request.host, NodeBucket())
            self._add_request(bucket, node, request, reads.get(request.host))
        for host, read in reads.items():
            self._add_read(bucket.nodes[host], read, requests)
        self._add_waits(bucket, requests)
        for run in runs:
            if run.done and run.run_id not in self._seen and len(bucket.run_ids) < self.MAX_FINISHED:
                self._seen.add(run.run_id)
                bucket.run_ids.append(run.run_id)
                for step, timing in run.nodes.items():
                    if timing.elapsed_ms > 0 and len(bucket.steps.get(step, ())) < self.MAX_DURATIONS:
                        bucket.steps.setdefault(step, []).append(round(timing.elapsed_ms, 1))
        self._dirty = True

    @staticmethod
    def _long_reads(requests: list[EngineRequestView]) -> dict[str, EngineRequestView]:
        """Per node, the reply reading the longest prompt from the start right now, if it is long."""
        reads: dict[str, EngineRequestView] = {}
        for r in requests:
            fresh = r.prompt_tokens - r.reused_tokens
            if r.phase == "prefill" and fresh >= LONG_READ_TOKENS:
                kept = reads.get(r.host)
                if kept is None or fresh > kept.prompt_tokens - kept.reused_tokens:
                    reads[r.host] = r
        return reads

    @staticmethod
    def _add_read(node: NodeBucket, read: EngineRequestView, requests: list[EngineRequestView]) -> None:
        node.long_read += 1
        others = [r for r in requests if r.host == read.host and r is not read and r.phase != "done"]
        if any(r.phase == "queued" or WorkflowHistory._slow(r) for r in others):
            node.held_polls += 1
        fresh = read.prompt_tokens - read.reused_tokens
        if fresh > node.read_tokens:
            node.read_tokens, node.read_reused, node.read_model = fresh, read.reused_tokens, read.model

    @staticmethod
    def _add_waits(bucket: HistoryBucket, requests: list[EngineRequestView]) -> None:
        """Per node, the reply waiting longest for its first word, counted once per poll."""
        waits: dict[str, float] = {}
        for r in requests:
            if r.phase in WAITING_PHASES:
                waits[r.host] = max(waits.get(r.host, 0.0), r.elapsed_seconds)
        for host, wait in waits.items():
            node = bucket.nodes[host]
            node.long_wait += wait >= LONG_WAIT_SECONDS
            node.max_wait = max(node.max_wait, round(wait, 1))

    @staticmethod
    def _slow(r: EngineRequestView) -> bool:
        if r.phase != "decode" or not r.tokens_per_second or not r.usual_tokens_per_second:
            return False
        return r.usual_tokens_per_second / r.tokens_per_second >= SLOW_RATIO

    def _add_request(
        self, bucket: HistoryBucket, node: NodeBucket, r: EngineRequestView, read: EngineRequestView | None
    ) -> None:
        if r.phase == "done":
            key = f"{r.host} {r.request_id}"
            if key not in self._seen and len(bucket.finished) < self.MAX_FINISHED:
                self._seen.add(key)
                fields = r.model_dump(include=set(FinishedReply.model_fields))
                bucket.finished.append(FinishedReply(key=key, started_at=self._clock() - r.elapsed_seconds, **fields))
            return
        node.running += 1
        node.queued += r.phase == "queued"
        held_up = read is not None and r is not read
        node.queued_in_read += held_up and r.phase == "queued"
        node.slow_in_read += held_up and self._slow(r)
        if r.phase == "decode" and r.tokens_per_second:
            node.decode += 1
            node.crawl += r.tokens_per_second < CRAWL_TPS
            node.min_tps = min(node.min_tps or r.tokens_per_second, r.tokens_per_second)
            ratio = r.usual_tokens_per_second / r.tokens_per_second if r.usual_tokens_per_second else 1.0
            node.ratio_sum += ratio
            node.slow += ratio >= SLOW_RATIO
            totals = node.tps_by_model.setdefault(r.model, [0.0, 0])
            totals[0] += r.tokens_per_second
            totals[1] += 1

    def _bucket(self) -> HistoryBucket:
        buckets = self.buckets()
        now = self._clock()
        if not buckets or now - buckets[-1].start >= self.BUCKET_SECONDS:
            buckets.append(HistoryBucket(start=now - now % self.BUCKET_SECONDS, first_poll=now, last_poll=now))
        buckets[-1].last_poll = now
        return buckets[-1]

    async def save_if_due(self) -> None:
        if not self._dirty or self._clock() - self._saved_at < self._save_every:
            return
        self._saved_at, self._dirty = self._clock(), False
        text = json.dumps([b.model_dump() for b in self.buckets()], separators=(",", ":"))
        self._save_every = self.SAVE_SECONDS * max(1.0, len(text) / 1_000_000)  # a big cluster: less often
        try:
            await asyncio.to_thread(self._write, text)
        except OSError as error:
            logger.warning("Could not save the workflow history: %s", error)

    def _write(self, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, self._path)

    def _load(self) -> None:
        if self._buckets is not None:
            return
        self._buckets = []
        try:
            self._buckets = [HistoryBucket(**b) for b in json.loads(self._path.read_text())]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as error:
            logger.warning("Ignoring an unreadable workflow history: %s", error)
        self._seen = self._keys(self._buckets)

    @staticmethod
    def _keys(buckets: list[HistoryBucket]) -> set[str]:
        return {f.key for b in buckets for f in b.finished} | {run_id for b in buckets for run_id in b.run_ids}


workflow_history = WorkflowHistory()
