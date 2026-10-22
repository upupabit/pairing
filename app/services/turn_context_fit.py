"""Fits a message's extra context (RAG excerpts, attached files' text) into the room the chat history leaves in the
context window, so a big attachment never pushes the prompt over num_ctx (the engine would refuse it).

The history itself is never trimmed for this: its start stays where chat_history_service.trim_history put it, so the
engine's prompt cache keeps matching and the next message doesn't re-read the whole chat. What doesn't fit is cut,
with a note for the model and a notice for the user (chat_service sends it as a "notice" event).
"""

# Characters per token. Latin text is about 4; other Characters take far more tokens per character
_LATIN_CHARS_PER_TOKEN = 4.0
_OTHER_CHARS_PER_TOKEN = 1.2
_TOKENS_PER_MESSAGE = 8  # chat-template markers around each message
_SAFETY = 0.9  # leave a tenth of the room unused: the estimate is not the engine's tokenizer


class TokenEstimate:
    @staticmethod
    def of(text: str) -> int:
        latin = len(text.encode("ascii", "ignore"))
        other = len(text) - latin
        return int(latin / _LATIN_CHARS_PER_TOKEN + other / _OTHER_CHARS_PER_TOKEN) + 1

    @classmethod
    def of_messages(cls, messages: list[dict]) -> int:
        return sum(cls.of(m.get("content") or "") + _TOKENS_PER_MESSAGE for m in messages)


class TurnContextFit:
    """The token room for this message's extra context, spent piece by piece in order."""

    def __init__(self, num_ctx: int, reserved_tokens: int, system_prompt: str, history: list[dict]) -> None:
        used = reserved_tokens + TokenEstimate.of(system_prompt) + TokenEstimate.of_messages(history)
        self.room = max(int((num_ctx - used) * _SAFETY), 0)
        self.notices: list[str] = []

    def take(self, text: str) -> bool:
        """Spends room on `text` if all of it fits."""
        cost = TokenEstimate.of(text)
        if cost > self.room:
            return False
        self.room -= cost
        return True

    def cut(self, filename: str, text: str) -> str:
        """`text`, or as much of its start as fits, with a note for the model when cut ("" when nothing fits)."""
        if self.take(text):
            return text
        kept = self._prefix_that_fits(text)
        share = round(100 * len(kept) / max(len(text), 1))
        if not kept:
            self.notices.append(f"{filename} didn't fit in the context window and was left out.")
            return ""
        self.room -= TokenEstimate.of(kept)
        self.notices.append(
            f"Only the first {share}% of {filename} fitted in the context window. "
            "For long documents, add them to the knowledge base."
        )
        return f"{kept}\n\n[Only the first {share}% of this file fitted; the rest was left out.]"

    def _prefix_that_fits(self, text: str) -> str:
        """The longest start of `text` within the room, ending at a line or word break when possible."""
        low, high = 0, len(text)
        while low < high:  # largest length whose estimate fits
            mid = (low + high + 1) // 2
            if TokenEstimate.of(text[:mid]) <= self.room:
                low = mid
            else:
                high = mid - 1
        prefix = text[:low]
        if low == len(text):
            return prefix
        for separator in ("\n", " "):
            at = prefix.rfind(separator)
            if at > low * 0.8:
                return prefix[:at]
        return prefix
