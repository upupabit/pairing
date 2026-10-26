"""Tests for services/reasoning_stages.py: stages picked from streamed reasoning (Gemma 4's numbered steps, Qwen's
bold headings), whatever the chunk boundaries, never a half-written heading."""

import pytest

from app.services.reasoning_stages import ReasoningStages

GEMMA = (
    '\nThinking Process:\n\n1.  **Analyze the Request:** The user said "Hi".\n'
    "2.  **Determine the Goal:** Reply warmly.\n    *   Option A\n    *   Option B\n"
    "3.  **Draft options:**\n    *   Option 1: Hello!\n"
)
QWEN = "**Understanding the question**\nThe user wants primes.\n\n**Listing them**\n2, 3, 5.\n"


def _stages(text: str, size: int) -> list[str]:
    stages = ReasoningStages()
    for i in range(0, len(text), size):
        stages.feed(text[i : i + size])
    return stages.labels


@pytest.mark.parametrize("size", [1, 3, 7, 1000])
def test_numbered_steps_are_stages_and_sub_points_are_not(size: int) -> None:
    assert _stages(GEMMA, size) == ["1. Analyze the Request", "2. Determine the Goal", "3. Draft options"]


@pytest.mark.parametrize("size", [1, 5, 1000])
def test_bold_heading_lines_are_stages(size: int) -> None:
    assert _stages(QWEN, size) == ["Understanding the question", "Listing them"]


def test_feed_says_when_a_stage_was_added_and_waits_for_the_line_end() -> None:
    stages = ReasoningStages()
    assert stages.feed("1.  **Analyze the Req") is False
    assert stages.feed("uest:** ok\n") is True
    assert stages.feed("plain text\n") is False
    assert stages.labels == ["1. Analyze the Request"]


def test_a_heading_ending_in_a_period_loses_it() -> None:
    stages = ReasoningStages()
    stages.feed("7.  **Final Output Generation.** (This matches the response.)\n")
    assert stages.labels == ["7. Final Output Generation"]


def test_long_labels_are_cut_and_the_list_is_bounded() -> None:
    stages = ReasoningStages()
    stages.feed("1. " + "x" * 200 + "\n")
    stages.feed("".join(f"{n}. Step\n" for n in range(2, 40)))
    assert len(stages.labels[0]) <= ReasoningStages.MAX_LABEL + 3
    assert len(stages.labels) == ReasoningStages.MAX_STAGES


@pytest.mark.asyncio
async def test_side_events_broadcast_new_stages_and_check_for_deletes(monkeypatch) -> None:
    from app.services import (
        reply_broadcast_service,
        reply_cross_instance_service,
        reply_side_events,
        tool_event_service,
    )

    published, checks, tools = [], [], []
    monkeypatch.setattr(reply_broadcast_service, "publish_reasoning", lambda cid, stages: published.append(stages))

    async def deleted(_db, _message):
        checks.append(1)
        return len(checks) >= 2

    async def record(_db, _message, event, _cid):
        tools.append(event)

    monkeypatch.setattr(reply_cross_instance_service, "deleted_elsewhere", deleted)
    monkeypatch.setattr(tool_event_service, "record", record)
    monkeypatch.setattr(reply_side_events.ReplySideEvents, "CHECK_SECONDS", 0.0)
    side = reply_side_events.ReplySideEvents(None, None, "c1")

    assert await side.handle({"tool": {"name": "search"}}) is False
    assert await side.handle({"reasoning": "1. **Analyze:** hi\n"}) is False
    assert await side.handle({"reasoning": "more thoughts "}) is True

    assert tools == [{"name": "search"}]
    assert published == [["1. Analyze"]]
