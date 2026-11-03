"""A chat as a Markdown file (GET /api/conversations/{id}/export)."""

import re
from datetime import datetime

from app.models import Conversation, Message
from app.services import conversation_service


class ChatExport:
    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation

    def markdown(self) -> str:
        conversation = self._conversation
        lines = [f"# {conversation.title or 'Chat'}", ""]
        details = [f"Model: {conversation.model}"] if conversation.model else []
        details.append(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines += [" · ".join(details), ""]
        for message in conversation_service.visible_messages(conversation):
            if message.role == "system" or not message.content.strip():
                continue
            lines += [f"## {self._speaker(message)}", f"*{self._time(message)}*", "", message.content.strip(), ""]
            if message.sources:
                lines += [f"Sources: {', '.join(message.sources)}", ""]
        return "\n".join(lines).rstrip() + "\n"

    def filename(self, extension: str) -> str:
        """A safe file name from the title, e.g. "trip-plan.md"."""
        slug = re.sub(r"[^\w\-]+", "-", (self._conversation.title or "chat").strip().lower(), flags=re.UNICODE)
        return f"{slug.strip('-')[:60] or 'chat'}.{extension}"

    def _speaker(self, message: Message) -> str:
        if message.role == "assistant":
            return "AI"
        return message.sender_display_name or "You"

    @staticmethod
    def _time(message: Message) -> str:
        moment = message.completed_at or message.created_at
        return moment.strftime("%Y-%m-%d %H:%M") if moment else ""
