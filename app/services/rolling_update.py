"""Admin settings > Update > "Update all servers": pAIring updates one server at a time, so the others keep
serving. The rollout is one app_settings row (ROLLOUT_KEY) that only the start/cancel calls and the leader
write; each server writes only its own `servers.update_state`. The leader picks the next server once the
current one reports a final state, and stops at the first error. Each server updates itself from GitHub
(PairingUpdate) and restarts with scripts/restart.sh; its migrations run under StartupLock on the way up.
While updating, a server shares its step and percent (`progress()`) in its row's details, for the progress bar.
"""

import asyncio
import copy
import logging
import uuid
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import SYSTEM_OWNER_ID, AppSetting, Server
from app.services import http_proxy_service
from app.services.db_clock import db_epoch
from app.services.server_registry import ServerRegistry, server_registry
from app.services.update_source import UpdateSourceService
from app.services.update_targets import PairingUpdate
from app.services.upload_jobs import ProgressThrottle

logger = logging.getLogger("llama_chat")

ROLLOUT_KEY = "rolling_update"
FINAL_STATES = ("done", "up_to_date", "needs_restart", "skipped")


class RolloutError(ValueError):
    """Shown to the admin: e.g. a rollout already running."""


class RollingUpdate:
    STEP_TIMEOUT_SECONDS = 900
    PROGRESS_SECONDS = 3.0

    def __init__(
        self,
        registry: ServerRegistry = server_registry,
        pairing_factory: Callable[..., PairingUpdate] = PairingUpdate,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._registry = registry
        self._pairing_factory = pairing_factory
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._pairing: PairingUpdate | None = None
        self._restart_pending = False
        self._progress: dict | None = None

    def progress(self) -> dict | None:
        """This server's own update step while it updates: step, total_steps, label and percent (or None)."""
        return copy.copy(self._progress)

    async def get(self, db: AsyncSession) -> dict | None:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, ROLLOUT_KEY))
        return copy.deepcopy(row.value) if row else None

    async def start(self, db: AsyncSession) -> dict:
        current = await self.get(db)
        if current and current["status"] == "running":
            raise RolloutError("An update of all servers is already running.")
        servers, now = await self._registry.servers(db)
        holder = (await db.execute(text("SELECT holder FROM leader_leases WHERE name = 'leader'"))).scalar()
        queue = [s.server_id for s in servers if s.is_primary and self._registry.online(s, now)]
        if not queue:
            raise RolloutError("No server is online.")
        queue.sort(key=lambda sid: sid == holder)  # the leader last: fewer leader changes
        rollout = {"id": uuid.uuid4().hex, "status": "running", "queue": queue, "current": None, "results": {}}
        # `order` keeps the servers in update order: a MySQL JSON column doesn't keep `results` in insertion order.
        timing = {"order": list(queue), "started_at": now, "finished_at": None, "durations": {}}
        await self._save(db, {**rollout, **timing, "current_since": now, "message": None})
        return await self.get(db)

    async def cancel(self, db: AsyncSession) -> dict | None:
        """Stops before the next server; one already updating finishes."""
        rollout = await self.get(db)
        if rollout and rollout["status"] == "running":
            finished_at = await db_epoch(db)
            rollout.update(status="cancelled", queue=[], message="Cancelled by an admin.", finished_at=finished_at)
            await self._save(db, rollout)
        return rollout

    async def leader_step(self, db: AsyncSession) -> None:
        rollout = await self.get(db)
        if not rollout or rollout["status"] != "running":
            return
        now = await db_epoch(db)
        if current := rollout["current"]:
            row = await db.get(Server, current)
            state = row.update_state if row and row.update_round == rollout["id"] else None
            if state and state.startswith(FINAL_STATES + ("error",)):
                rollout["results"][current] = state
                rollout.setdefault("durations", {})[current] = now - rollout["current_since"]
            if state and state.startswith(FINAL_STATES):
                rollout["current"] = None
            elif state and state.startswith("error"):
                rollout.update(status="stopped", message=f"{current}: {state}")
            elif now - rollout["current_since"] > self.STEP_TIMEOUT_SECONDS:
                rollout.update(status="stopped", message=f"{current} did not finish in time.")
            else:
                return
        if rollout["status"] == "running" and rollout["current"] is None:
            if rollout["queue"]:
                rollout.update(current=rollout["queue"].pop(0), current_since=now)
            else:
                rollout["status"] = "finished"
        if rollout["status"] != "running":
            rollout["finished_at"] = now
        await self._save(db, rollout)

    async def server_step(self, db: AsyncSession) -> None:
        """A primary's part: update when it is its turn; after the restart, report "done"."""
        rollout = await self.get(db)
        if not rollout or rollout["status"] != "running" or rollout["current"] != self._registry.server_id:
            return
        row = await self._registry.own_row(db)
        if row and row.update_round == rollout["id"]:
            if row.update_state == "restarting" and not self._restart_pending:
                await self._registry.set_update_state(db, rollout["id"], "done")  # this is the new process
            return
        if self._task is None:
            await self._registry.set_update_state(db, rollout["id"], "updating")
            self._task = asyncio.create_task(self._run(rollout["id"]))

    async def _run(self, round_id: str) -> None:
        try:
            state = await self._update()
        except Exception as exc:  # noqa: BLE001 - reported to the admin, never left "updating"
            logger.exception("Update of this server failed.")
            state = f"error: {exc}"
        self._progress = None
        async with self._session_factory() as db:
            await self._registry.set_update_progress(db, None)
            await self._registry.set_update_state(db, round_id, state)
        if state == "restarting":
            self._restart_pending = True
            self._pairing.restart()
        else:
            self._task = None

    async def _update(self) -> str:
        async with self._session_factory() as db:
            proxy_url = (await http_proxy_service.get_http_proxy_config(db)).proxy_url()
            sources = UpdateSourceService(db)  # the same on every server: shared database
            remote, token = await sources.remote("pairing"), await sources.token("pairing")
        self._pairing = self._pairing_factory(proxy_url, remote=remote, token=token)
        if self._pairing.in_container():
            return "skipped: running in a container, update its image"
        done = None
        throttle = ProgressThrottle(self.PROGRESS_SECONDS)
        async for event in self._pairing.updater.update_stream():
            if "error" in event:
                return f"error: {event['error']}"
            if event.get("done"):
                done = event
            elif self._track(event) and throttle.due():
                async with self._session_factory() as db:
                    await self._registry.set_update_progress(db, self.progress())
        if not done or not done.get("changed"):
            return "up_to_date"
        info = self._pairing.restart_info()
        return "restarting" if info.can_restart else f"needs_restart: {info.hint}"

    def _track(self, event: dict) -> bool:
        """Folds one update event into `_progress`; True when it changed."""
        before = self._progress
        current = dict(before or {"step": 1, "total_steps": 3, "label": "Starting", "percent": None})
        if "step" in event:
            if event["step"] != current["step"]:
                current["percent"] = None
            current.update(step=event["step"], total_steps=event.get("total_steps", current["total_steps"]))
        if "step_label" in event:
            current["label"] = event["step_label"]
        if event.get("total"):
            current["percent"] = min(100, round(100 * event.get("completed", 0) / event["total"]))
        self._progress = current
        return current != before

    async def _save(self, db: AsyncSession, value: dict) -> None:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, ROLLOUT_KEY))
        if row is None:
            db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=ROLLOUT_KEY, value=value))
        else:
            row.value = value
        await db.commit()


rolling_update = RollingUpdate()
