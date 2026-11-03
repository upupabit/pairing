"""A reply's speed, shown under it: time to first token, total time, and tokens/sec.

Times are measured here, so every engine has them. Token counts come from the engine's final
{"usage": ...} chunk (llama.cpp timings, Matricxon's done line); cloud connectors send none.
A tool loop makes several model calls, so usage chunks add up.
"""

import time
from collections.abc import Callable


class ReplyStats:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started = clock()
        self._first_text: float | None = None
        self._output_tokens = 0
        self._output_ms = 0.0
        self._prompt_tokens = 0
        self._has_usage = False

    def text(self) -> None:
        """Call on every text chunk; only the first one counts."""
        if self._first_text is None:
            self._first_text = self._clock()

    def usage(self, usage: dict) -> None:
        self._has_usage = True
        self._output_tokens += int(usage.get("output_tokens") or 0)
        self._output_ms += float(usage.get("output_ms") or 0)
        self._prompt_tokens += int(usage.get("prompt_tokens") or 0)

    def result(self) -> dict | None:
        """None when no text came (nothing to time)."""
        if self._first_text is None:
            return None
        now = self._clock()
        stats: dict = {
            "first_token_ms": round((self._first_text - self._started) * 1000),
            "total_ms": round((now - self._started) * 1000),
        }
        if self._has_usage and self._output_tokens:
            # The engine's own generation time if given, else from the first token to the end.
            seconds = self._output_ms / 1000 or (now - self._first_text)
            stats["output_tokens"] = self._output_tokens
            stats["prompt_tokens"] = self._prompt_tokens or None
            stats["tokens_per_second"] = round(self._output_tokens / seconds, 1) if seconds > 0 else None
        return stats

    @staticmethod
    def from_llamacpp(timings: dict) -> dict:
        return {
            "output_tokens": timings.get("predicted_n"),
            "output_ms": timings.get("predicted_ms"),
            "prompt_tokens": timings.get("prompt_n"),
        }

    @staticmethod
    def from_matricxon(done: dict) -> dict:
        # Its eval_duration starts with the prompt read (prompt_eval_duration): only the rest is generation.
        eval_ns = max((done.get("eval_duration") or 0) - (done.get("prompt_eval_duration") or 0), 0)
        return {
            "output_tokens": done.get("eval_count"),
            "output_ms": eval_ns / 1_000_000,
            "prompt_tokens": done.get("prompt_eval_count"),
        }
