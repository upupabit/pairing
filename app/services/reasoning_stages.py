"""The stages of a model's reasoning, picked from its streamed text for the chat's live "Reasoning..." list: numbered
top-level steps ("1.  **Analyze the request:**", Gemma 4) or bold heading lines ("**Planning the answer**", Qwen).
Sub-points (indented bullets) aren't stages. Only finished lines are read, so a heading is never shown half-written."""

import re

_NUMBERED = re.compile(r"^(\d{1,2})\.\s+(.+)$")
_BOLD_LINE = re.compile(r"^\*\*(.+?)\*\*:?\s*$")
_LEADING_BOLD = re.compile(r"^\*\*(.+?)\*\*")


class ReasoningStages:
    MAX_STAGES = 12
    MAX_LABEL = 70

    def __init__(self) -> None:
        self.labels: list[str] = []
        self._pending = ""

    def feed(self, text: str) -> bool:
        """True when this text finished a line that added a stage."""
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        added = False
        for line in lines:
            label = self._label(line)
            if label and len(self.labels) < self.MAX_STAGES and (not self.labels or self.labels[-1] != label):
                self.labels.append(label)
                added = True
        return added

    @classmethod
    def _label(cls, line: str) -> str | None:
        if line[:1].isspace():  # an indented sub-point
            return None
        line = line.strip()
        numbered = _NUMBERED.match(line)
        if numbered:
            text = numbered.group(2)
            bold = _LEADING_BOLD.match(text)  # "**Title:** details": the title alone
            text = bold.group(1) if bold else text.split(":", 1)[0]
        else:
            bold = _BOLD_LINE.match(line)
            if not bold:
                return None
            text = bold.group(1)
        text = text.replace("**", "").strip().rstrip(":.").strip()
        if not text:
            return None
        if len(text) > cls.MAX_LABEL:
            text = text[: cls.MAX_LABEL - 1].rstrip() + "…"
        return f"{numbered.group(1)}. {text}" if numbered else text
