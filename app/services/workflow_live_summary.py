"""Keeps the Stats live view light on a large cluster: past `DETAILED` chats, only the ones worth a status row (this
instance's, then the slowest) are sent in full; the rest become counts per step (LiveCrowd), which the diagram adds
to its ×N figures. A small cluster is sent unchanged.
"""

from dataclasses import dataclass

from app.schemas.workflow_live import EngineCrowd, EngineRequestView, LiveCrowd, LiveRunView

# Steps that pass each written token on to the browser (LIVE_COUNT_NODES in workflow_diagram_live_map.js).
STREAMING_STEPS = frozenset({"broadcast_publish", "relay_back"})


@dataclass
class _Chat:
    run: LiveRunView | None
    request: EngineRequestView | None

    @property
    def done(self) -> bool:
        return self.run.done if self.run else self.request.phase == "done"

    @property
    def slowness(self) -> float:
        r = self.request
        if r and r.tokens_per_second and r.usual_tokens_per_second:
            return r.usual_tokens_per_second / r.tokens_per_second
        return 0.0

    @property
    def elapsed_seconds(self) -> float:
        return self.run.elapsed_ms / 1000 if self.run else self.request.elapsed_seconds


class LiveSummary:
    DETAILED = 24  # chats sent in full: the status box shows 4, the diagram labels its steps from them
    FINISHED = 4

    def __init__(self, runs: list[LiveRunView], requests: list[EngineRequestView]) -> None:
        claimed = {run.request_id: run for run in runs if run.request_id}
        by_id = {r.request_id: r for r in requests}
        self._chats = [_Chat(run, by_id.get(run.request_id)) for run in runs]
        self._chats += [_Chat(None, r) for r in requests if r.request_id not in claimed]
        self._busy_nodes = len({r.host for r in requests if r.phase != "done"})

    def split(self) -> tuple[list[LiveRunView], list[EngineRequestView], LiveCrowd | None]:
        """(runs and replies sent in full, counts for the rest or None when everything is sent)."""
        if len(self._chats) <= self.DETAILED:
            return self._runs(self._chats), self._requests(self._chats), None
        running = sorted(
            (c for c in self._chats if not c.done),
            key=lambda c: (c.run is None, -c.slowness, -c.elapsed_seconds),  # this instance's first, then slowest
        )
        finished = [c for c in self._chats if c.done][: self.FINISHED]
        kept = running[: self.DETAILED - len(finished)]
        crowd = self._crowd(running[len(kept) :])
        kept += finished
        return self._runs(kept), self._requests(kept), crowd

    def _crowd(self, chats: list[_Chat]) -> LiveCrowd:
        crowd = LiveCrowd(running=len(chats), busy_nodes=self._busy_nodes)
        for chat in chats:
            if chat.request and chat.request.phase != "done":
                phase = crowd.engine.setdefault(chat.request.phase, EngineCrowd())
                phase.replies += 1
                phase.tokens_per_second += chat.request.tokens_per_second or 0.0
            for node_id in self._app_steps(chat):
                crowd.app[node_id] = crowd.app.get(node_id, 0) + 1
        for phase in crowd.engine.values():
            phase.tokens_per_second = round(phase.tokens_per_second, 1)
        return crowd

    @staticmethod
    def _app_steps(chat: _Chat) -> set[str]:
        """This instance's busy steps for a counted chat, as the diagram would light them."""
        if chat.run is None:
            return set()
        steps = {node_id for node_id, timing in chat.run.nodes.items() if timing.active}
        phase = chat.request.phase if chat.request else None
        if phase not in (None, "done"):
            steps.discard("ml_engine_server")  # counted with the engine phase
        if phase == "decode":
            steps |= STREAMING_STEPS  # light up per token, not while "active"
        return steps

    @staticmethod
    def _runs(chats: list[_Chat]) -> list[LiveRunView]:
        return [c.run for c in chats if c.run]

    @staticmethod
    def _requests(chats: list[_Chat]) -> list[EngineRequestView]:
        return [c.request for c in chats if c.request]
