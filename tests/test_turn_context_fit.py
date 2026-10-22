"""Tests for services/turn_context_fit.py: fitting RAG excerpts and attached files into the context window."""

import pytest

from app.schemas import ConversationCreate
from app.services import (
    chat_service,
    context_window_setting,
    conversation_service,
    model_catalog_service,
    reply_generation_service,
)
from app.services.chat_attachment_service import AttachmentInfo
from app.services.turn_context_fit import TokenEstimate, TurnContextFit


def test_non_latin_text_counts_as_more_tokens():
    assert TokenEstimate.of("a" * 400) == 101
    assert TokenEstimate.of("א" * 120) == 101  # Hebrew: far fewer characters per token


def _fit(room_tokens: int) -> TurnContextFit:
    fit = TurnContextFit(num_ctx=10_000, reserved_tokens=0, system_prompt="", history=[])
    fit.room = room_tokens
    return fit


def test_text_that_fits_is_kept_whole():
    fit = _fit(100)
    assert fit.cut("a.txt", "short text") == "short text"
    assert fit.notices == []


def test_a_long_file_is_cut_with_a_note_and_a_notice():
    fit = _fit(100)
    text = " ".join(["word"] * 400)  # ~500 tokens

    kept = fit.cut("report.txt", text)

    assert kept.startswith("word word") and "[Only the first" in kept
    assert TokenEstimate.of(kept.split("\n\n[Only")[0]) <= 100
    assert len(fit.notices) == 1 and "report.txt" in fit.notices[0] and "knowledge base" in fit.notices[0]


def test_a_cut_ends_at_a_line_break_when_one_is_near():
    fit = _fit(30)
    text = "\n".join(f"line {i} " + "x" * 12 for i in range(100))

    kept = fit.cut("lines.txt", text).split("\n\n[Only")[0]

    assert kept.endswith("x")  # a whole line, not cut mid-line
    assert text.startswith(kept)


def test_nothing_fits_leaves_the_file_out():
    fit = _fit(0)
    assert fit.cut("big.pdf", "anything") == ""
    assert fit.notices == ["big.pdf didn't fit in the context window and was left out."]


def test_take_spends_room_until_it_runs_out():
    fit = _fit(60)
    excerpts = ["e" * 120, "e" * 120, "e" * 120]  # ~31 tokens each

    assert [fit.take(text) for text in excerpts] == [True, False, False]


def test_the_room_is_what_the_history_leaves():
    history = [{"role": "user", "content": "a" * 400}]  # ~101 + 8 tokens
    fit = TurnContextFit(num_ctx=1000, reserved_tokens=500, system_prompt="", history=history)
    assert fit.room == int((1000 - 500 - 101 - 8) * 0.9)


@pytest.mark.asyncio
async def test_a_huge_attachment_is_cut_to_the_window_and_the_sender_is_told(db, user, tmp_path, monkeypatch):
    captured: dict = {}

    async def fake_chat_stream(_model, messages, _params):
        captured["messages"] = messages
        yield "ok"

    async def installed():
        return ["fake-model"]

    async def small_window(_db):
        return 4096  # minus the default 1,024-token reply reserve

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat_service, "ATTACHMENTS_DIR", tmp_path)
    monkeypatch.setattr(context_window_setting, "get_num_ctx", small_window)
    path = tmp_path / "huge.txt"
    path.write_text("\n".join(f"Row {i}: some data about the item" for i in range(1500)))  # ~13,000 tokens
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)

    events = [
        event
        async for event in chat_service.build_reply_stream(
            db,
            conversation,
            user,
            "summarize",
            attachments=[AttachmentInfo(path=path, filename="huge.txt", type="text")],
        )
    ]

    notices = [event["notice"] for event in events if "notice" in event]
    assert len(notices) == 1 and "huge.txt" in notices[0]
    last_user = [m for m in captured["messages"] if m["role"] == "user"][-1]["content"]
    assert "Row 0:" in last_user and "Row 1499:" not in last_user and "[Only the first" in last_user
    assert TokenEstimate.of_messages(captured["messages"]) + 1024 <= 4096  # fits, with the reply's room left


@pytest.mark.asyncio
async def test_a_small_attachment_needs_no_notice(db, user, tmp_path, monkeypatch):
    async def fake_chat_stream(_model, _messages, _params):
        yield "ok"

    async def installed():
        return ["fake-model"]

    monkeypatch.setattr(model_catalog_service, "installed_chat_models", installed)
    monkeypatch.setattr(reply_generation_service, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(chat_service, "ATTACHMENTS_DIR", tmp_path)
    path = tmp_path / "note.txt"
    path.write_text("a short note")
    conversation = await conversation_service.create_conversation(db, ConversationCreate(model="fake-model"), user)

    events = [
        event
        async for event in chat_service.build_reply_stream(
            db, conversation, user, "read it", attachments=[AttachmentInfo(path=path, filename="note.txt", type="text")]
        )
    ]

    assert not any("notice" in event for event in events)
