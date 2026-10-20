"""Writes the `--models-preset` INI llama-server's router reads: one section per runnable installed model
(projectors only appear as their model's `mmproj`), plus `[*]` with the context size every chat uses
(Settings > System > Context window). llama-server re-reads it on `GET /models?reload=1`, so a pull, delete or
context change applies without a restart; a loaded model whose section changed is unloaded.
"""

from pathlib import Path

from app.config import DATA_DIR, EMBEDDING_NUM_CTX
from app.services.gguf_model_store import StoredModel
from app.services.llamacpp_models import LlamaCppModelName

PRESET_PATH = DATA_DIR / "llamacpp" / "models.ini"


class LlamaCppPreset:
    def __init__(self, entries: list[tuple[StoredModel, StoredModel | None, list[str]]], num_ctx: int, slots: int):
        self._entries = entries
        self._num_ctx = num_ctx
        # llama-server splits the context across parallel slots, so each slot keeps the full context window.
        self._slots = max(slots, 1)

    def render(self) -> str:
        lines = ["version = 1", "", "[*]", f"ctx-size = {self._num_ctx * self._slots}", ""]
        for model, projector, capabilities in self._entries:
            if model.is_projector or not capabilities:
                continue
            lines += [f"[{LlamaCppModelName.to_router(model.tag)}]", f"model = {model.path}"]
            if "embedding" in capabilities:
                lines += ["embeddings = true", f"ctx-size = {EMBEDDING_NUM_CTX * self._slots}"]
            elif "rerank" in capabilities:
                lines += ["embeddings = true", "pooling = rank", "reranking = true"]
            elif projector is not None:
                lines += [f"mmproj = {projector.path}"]
            lines.append("")
        return "\n".join(lines)

    def write(self, path: Path | None = None) -> bool:
        """True if the file changed (a reload is then worth asking for)."""
        path = path or PRESET_PATH
        text = self.render()
        if path.exists() and path.read_text() == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)
        return True
