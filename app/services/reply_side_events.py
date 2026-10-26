"""A reply stream's non-text chunks, split from reply_generation_service for the file-size rule: MCP tool calls
({"tool": event}) and reasoning ({"reasoning": text}, params["reasoning_ticks"]). Reasoning text isn't kept or shown,
only its stages (reasoning_stages.py), broadcast as they appear; and since a long reasoning phase has no reply text, the
cross-instance delete check runs on these chunks too (else a deleted reply would generate on, unwatched)."""

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.services import reply_broadcast_service, reply_cross_instance_service, tool_event_service
from app.services.reasoning_stages import ReasoningStages


class ReplySideEvents:
    CHECK_SECONDS = 0.4  # like reply_generation_service._FLUSH_INTERVAL_SECONDS for text

    def __init__(self, db: AsyncSession, message: Message, conversation_id: str) -> None:
        self._db = db
        self._message = message
        self._conversation_id = conversation_id
        self._stages = ReasoningStages()
        self._last_check = time.monotonic()

    async def handle(self, chunk: dict) -> bool:
        """True when the reply must stop: deleted, possibly through another instance."""
        if "tool" in chunk:
            await tool_event_service.record(self._db, self._message, chunk["tool"], self._conversation_id)
            return False
        text = chunk.get("reasoning")
        if isinstance(text, str) and self._stages.feed(text):
            reply_broadcast_service.publish_reasoning(self._conversation_id, list(self._stages.labels))
        now = time.monotonic()
        if now - self._last_check < self.CHECK_SECONDS:
            return False
        self._last_check = now
        return await reply_cross_instance_service.deleted_elsewhere(self._db, self._message)
