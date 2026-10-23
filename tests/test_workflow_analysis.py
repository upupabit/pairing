"""Tests for services/workflow_history.py, services/workflow_analysis.py and the analysis route."""

from pathlib import Path

import pytest

from app.routers import workflow_live
from app.schemas.workflow_live import EngineRequestView, LiveNodeTiming, LiveRunView
from app.services.workflow_analysis import WorkflowAnalyzer
from app.services.workflow_history import WorkflowHistory


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _reply(
    host: str, i: int = 0, phase: str = "decode", tps: float = 10.0, usual: float = 10.0, **extra
) -> EngineRequestView:
    return EngineRequestView(
        host=host, request_id=f"{host}-{i}", model="m", phase=phase, tokens_per_second=tps,
        usual_tokens_per_second=usual, **{"elapsed_seconds": 1.0, **extra},
    )  # fmt: skip


def _history(tmp_path: Path, clock: Clock) -> WorkflowHistory:
    return WorkflowHistory(tmp_path / "history.json", clock)


def _poll(
    history: WorkflowHistory, clock: Clock, requests, hosts=("a", "b", "c"), down=None, runs=(), times=10
) -> None:
    for _ in range(times):
        history.record(list(hosts), down or {}, list(requests), list(runs), {"rag_rerank": 400.0})
        clock.now += 0.5


def _report(history: WorkflowHistory):
    return WorkflowAnalyzer(history.buckets(), history.WINDOW_SECONDS).report()


def test_history_keeps_only_the_window(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a")])
    clock.now += history.WINDOW_SECONDS + 30
    _poll(history, clock, [_reply("a")], times=2)

    assert len(history.buckets()) == 1
    assert _report(history).polls == 2


def test_history_counts_a_finished_reply_once(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a", phase="done", load_seconds=4.0)], times=30)

    report = _report(history)

    assert report.replies_finished == 1
    assert report.models[0].loads == 1
    assert any(f.title == "m was loaded once" and f.level == "info" for f in report.findings)


def test_chats_waiting_for_the_same_load_count_it_once(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    history.WINDOW_SECONDS = 10_000
    together = [_reply("a", i, phase="done", load_seconds=6.0, elapsed_seconds=20.0 + 90 * i) for i in range(2)]
    _poll(history, clock, together[:1], times=1)
    clock.now += 90  # the second chat, sent with the first, finishes much later
    _poll(history, clock, together[1:], times=1)
    clock.now += 600  # much later: unloaded and loaded again
    _poll(history, clock, [_reply("a", 9, phase="done", load_seconds=5.0)], times=1)

    report = WorkflowAnalyzer(history.buckets(), 10_000).report()

    assert (report.models[0].waited, report.models[0].loads) == (3, 2)
    assert [f.title for f in report.findings] == ["m was loaded 2 times"]


@pytest.mark.asyncio
async def test_history_survives_a_restart(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a")])
    await history.save_if_due()

    restored = _history(tmp_path, clock)

    assert sum(b.polls for b in restored.buckets()) == 10
    clock.now += history.WINDOW_SECONDS + 30
    assert _history(tmp_path, clock).buckets() == []  # too old once loaded


def test_analysis_flags_an_unreachable_and_a_slow_node(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    replies = [_reply("a"), _reply("b", tps=3.0, usual=10.0)]
    _poll(history, clock, replies, down={"c": "c: All connection attempts failed"})

    report = _report(history)

    titles = [f.title for f in report.findings]
    assert titles[:2] == ["c is unreachable", "b is slower than usual"]  # crit first
    assert report.nodes[0].host == "c"
    assert report.covered_seconds == pytest.approx(5.0)


def test_a_weaker_node_is_reported_once_not_as_slow(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    replies = [_reply("a"), _reply("b"), _reply("c"), _reply("d", tps=4.0, usual=4.0)]
    _poll(history, clock, replies, hosts=("a", "b", "c", "d"))

    findings = _report(history).findings

    assert [f.level for f in findings] == ["info"]
    assert "consistently slower" in findings[0].title and "d" in findings[0].detail


def test_analysis_reports_slow_app_steps(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    runs = [
        LiveRunView(run_id=f"r{i}", model="m", elapsed_ms=1.0, done=True, chunks=0,
                    nodes={"rag_rerank": LiveNodeTiming(active=False, elapsed_ms=1500.0, count=1),
                           "relay_back": LiveNodeTiming(active=False, elapsed_ms=0.0, count=40)})
        for i in range(4)
    ]  # fmt: skip
    _poll(history, clock, [], runs=runs)

    report = _report(history)

    assert [s.step for s in report.steps] == ["rag_rerank"]  # the 0 ms step is left out, not an error
    assert report.steps[0].runs == 4 and report.steps[0].usual_ms == 400.0
    assert report.findings[0].subject == "rag_rerank"


def test_a_saved_history_with_an_empty_step_still_reports(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a")])
    history.buckets()[0].steps["relay_back"] = []

    assert _report(history).steps == []


@pytest.mark.asyncio
async def test_analysis_route_reports_the_shared_history(admin_user, tmp_path: Path, monkeypatch) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a")])
    monkeypatch.setattr(workflow_live.workflow_live_service, "history", history)

    async def frame() -> tuple[str, bool]:
        return "", False

    monkeypatch.setattr(workflow_live.workflow_live_service, "frame", frame)

    report = await workflow_live.get_analysis(_admin=admin_user)

    assert report.polls == 10 and report.nodes_seen == 3


def test_a_long_read_holding_up_other_replies_is_the_finding_not_its_queue(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    reading = _reply("a", 1, phase="prefill", tps=None, prompt_tokens=4983, reused_tokens=79, prefilled_tokens=1024)
    waiting = _reply("a", 2, phase="queued", tps=None)
    _poll(history, clock, [reading, waiting], hosts=("a",), times=80)  # 40 s

    findings = _report(history).findings

    assert [(f.level, f.title) for f in findings] == [("crit", "A long prompt read held up other replies on a")]
    assert "4,904 prompt tokens of m" in findings[0].detail
    assert "only 79 of 4,983 came from the cache" in findings[0].detail
    assert "waited for a free model slot" in findings[0].detail


def test_a_long_read_alone_is_not_a_problem(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    reading = _reply("a", 1, phase="prefill", tps=None, prompt_tokens=4983, reused_tokens=79)
    _poll(history, clock, [reading], hosts=("a",), times=80)

    assert _report(history).findings == []


def test_a_queue_without_a_long_read_is_still_reported(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a", 1), _reply("a", 2, phase="queued", tps=None)], hosts=("a",))

    assert [f.title for f in _report(history).findings] == ["Replies queue on a"]


def test_replies_stuck_for_minutes_are_red_even_without_a_usual_speed(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    writing = _reply("a", 1, usual=None, tps=3.0)
    stuck = _reply("a", 2, phase="queued", tps=None, usual=None, elapsed_seconds=220.0)
    _poll(history, clock, [writing, stuck], hosts=("a",), times=80)

    findings = _report(history).findings

    assert [(f.level, f.title) for f in findings] == [("crit", "Matricxon on a is overloaded")]
    assert findings[0].detail.startswith("Replies waited up to 3m 40s before their first word")


def test_writing_at_a_crawl_is_red_even_without_a_usual_speed(tmp_path: Path) -> None:
    clock = Clock()
    history = _history(tmp_path, clock)
    _poll(history, clock, [_reply("a", 1, tps=0.25, usual=None)], hosts=("a",))

    findings = _report(history).findings

    assert [f.level for f in findings] == ["crit"]
    assert "below 1 tok/s (slowest 0.25 tok/s)" in findings[0].detail
