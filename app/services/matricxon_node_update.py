"""One Matricxon node's part in "Update all nodes" (matricxon_rollout.py): ask it to update itself
(../matricxon/app/update/self_update.py, POST/GET /api/update), follow its step and percent, wait until it is
back on the new commit, and in a cluster until it is a member with a quorum again. Returns the node's result
in the same words as a pAIring server's: done, up_to_date, skipped: ..., error: ...
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from app.services.update_source import GitRemote

ReportFn = Callable[[str, dict | None], Awaitable[None]]


class NodeUpdate:
    POLL_SECONDS = 2.0
    UPDATE_TIMEOUT = 900
    RESTART_TIMEOUT = 600
    REJOIN_TIMEOUT = 300

    def __init__(
        self, client: httpx.AsyncClient, host: str, cluster: bool, report: ReportFn, remote: GitRemote | None = None
    ) -> None:
        self._client = client
        self._remote = remote  # a chosen repository, sent along; None: the node's own origin
        self._host = host.rstrip("/")
        self._cluster = cluster
        self._report = report  # (stage, progress) for the progress bar

    async def run(self) -> str:
        try:
            before = await self._get("/api/version")
        except httpx.HTTPError as exc:
            return f"error: not reachable ({str(exc) or type(exc).__name__})"
        started = await self._start(before.get("version"))
        if started is not None:
            return started
        result = await self._follow_update()
        if result != "restarting":
            return result
        await self._report("restarting", None)
        if not await self._until(self._is_back(before.get("commit")), self.RESTART_TIMEOUT):
            return "error: did not come back after its restart"
        if self._cluster:
            await self._report("rejoining", None)
            if not await self._until(self._has_rejoined, self.REJOIN_TIMEOUT):
                return "error: restarted, but did not rejoin the cluster with a quorum"
        return "done"

    async def _start(self, version: str | None) -> str | None:
        """None when the update started (or one already runs); else the node's result."""
        try:
            body = self._remote.to_request() if self._remote else None
            resp = await self._client.post(f"{self._host}/api/update", json=body)
        except httpx.HTTPError as exc:
            return f"error: not reachable ({str(exc) or type(exc).__name__})"
        if resp.status_code == 404:
            return (
                f"error: this node runs an older Matricxon ({version or 'unknown version'}) that can't update "
                "itself yet: update it once on its machine (git pull, then restart it)"
            )
        detail = self._detail(resp)
        if resp.status_code == 409 and "already running" not in detail:
            return f"skipped: {detail}"  # a container or an install without git
        if resp.status_code in (401, 403):
            return "error: refused: set the cluster's admin secret on the Cluster page"
        if not resp.is_success and resp.status_code != 409:
            return f"error: {detail or f'HTTP {resp.status_code}'}"
        return None

    async def _follow_update(self) -> str:
        """restarting, up_to_date or error: ...; reports each step on the way."""
        deadline = time.monotonic() + self.UPDATE_TIMEOUT
        while time.monotonic() < deadline:
            try:
                status = await self._get("/api/update")
            except httpx.HTTPError:
                status = {"state": "restarting"}  # gone already: its restart began
            state = status.get("state")
            if state in ("restarting", "up_to_date"):
                return state
            if state == "error":
                return f"error: {status.get('error') or 'the update failed'}"
            if state == "updating":
                keys = ("step", "total_steps", "label", "percent")
                await self._report("updating", {k: status.get(k) for k in keys})
            await asyncio.sleep(self.POLL_SECONDS)
        return "error: the update did not finish in time"

    def _is_back(self, commit_before: str | None) -> Callable[[], Awaitable[bool]]:
        async def check() -> bool:
            version = await self._get("/api/version")
            return commit_before is None or version.get("commit") != commit_before

        return check

    async def _has_rejoined(self) -> bool:
        status = await self._get("/api/consensus/status")
        return bool(status.get("enabled") and status.get("has_quorum"))

    async def _until(self, check: Callable[[], Awaitable[bool]], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if await check():
                    return True
            except (httpx.HTTPError, ValueError):
                pass  # still restarting
            await self._report(None, None)  # keeps the rollout fresh while waiting
            await asyncio.sleep(self.POLL_SECONDS)
        return False

    async def _get(self, path: str) -> dict:
        resp = await self._client.get(f"{self._host}{path}")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _detail(resp: httpx.Response) -> str:
        try:
            return str(resp.json().get("detail") or "")
        except ValueError:
            return ""
