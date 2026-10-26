"""What the active engine reports a model can do ("tools", "thinking", "vision", ...), from its model list, cached
briefly so a chat or a reply doesn't pay for an extra engine call each time."""

import time

from app.services import inference_client
from app.services.inference_client import InferenceError


class ModelCapabilities:
    SECONDS = 60.0

    def __init__(self) -> None:
        self._until = 0.0
        self._models: list[dict] = []

    async def of(self, model: str) -> list[str] | None:
        """The model's capabilities, or None when unknown (engine unreachable, model not listed, or a list without
        them, like a remote llama-server's)."""
        now = time.monotonic()
        if now >= self._until:
            try:
                self._models = await inference_client.list_models()
            except InferenceError:
                return None
            self._until = now + self.SECONDS
        entry = next((m for m in self._models if m.get("name") == model), None)
        return entry.get("capabilities") if entry else None

    def forget(self) -> None:
        """Next call asks the engine again (after a pull, delete or engine switch)."""
        self._until = 0.0


model_capabilities = ModelCapabilities()
