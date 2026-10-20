"""The shared GGUF models folder Matricxon and llama.cpp both use: `<root>/hf.co/<repo>/<file>.gguf`, each with a
`<stem>.gguf.json` sidecar (Matricxon's InstalledModel shape, written by gguf_direct_puller). A model pulled
under either engine is installed for both, with one copy on disk.

Matricxon's own conventions are followed: the sidecar's location (not its `path`) says where the file is, and a
vision projector pairs with the models in its own folder (`architecture == "clip"`). Matricxon's tag aliases
are not read here.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("llama_chat")

SIDECAR_SUFFIX = ".gguf.json"
PROJECTOR_ARCHITECTURE = "clip"


@dataclass(frozen=True)
class StoredModel:
    tag: str
    path: Path
    architecture: str
    capabilities: list[str]
    size_bytes: int
    parameter_size: str
    context_length: int

    @property
    def is_projector(self) -> bool:
        return self.architecture == PROJECTOR_ARCHITECTURE


class GgufModelStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def models(self) -> list[StoredModel]:
        """Every model with a readable sidecar and its file present; a broken sidecar is skipped, not fatal."""
        if not self._root.is_dir():
            return []
        found = []
        for sidecar in sorted(self._root.rglob(f"*{SIDECAR_SUFFIX}")):
            model = self._load(sidecar)
            if model is not None:
                found.append(model)
        return found

    def get(self, tag: str) -> StoredModel | None:
        return next((m for m in self.models() if m.tag == tag), None)

    def projector_for(self, model: StoredModel, models: list[StoredModel] | None = None) -> StoredModel | None:
        """The clip file in `model`'s folder, if any (Matricxon's pairing rule)."""
        if model.is_projector:
            return None
        candidates = self.models() if models is None else models
        return next((m for m in candidates if m.is_projector and m.path.parent == model.path.parent), None)

    def delete(self, tag: str) -> bool:
        """Removes the file and its sidecar, then empty parent folders up to the root. False if not installed."""
        model = self.get(tag)
        if model is None:
            return False
        (model.path.parent / f"{model.path.stem}{SIDECAR_SUFFIX}").unlink(missing_ok=True)
        model.path.unlink(missing_ok=True)
        self._prune_empty(model.path.parent)
        return True

    def _prune_empty(self, directory: Path) -> None:
        while directory != self._root and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent

    @staticmethod
    def _load(sidecar: Path) -> StoredModel | None:
        try:
            data = json.loads(sidecar.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Skipping unreadable model sidecar %s: %s", sidecar, exc)
            return None
        path = sidecar.parent / sidecar.name.removesuffix(".json")
        if not path.is_file() or not data.get("tag"):
            return None
        return StoredModel(
            tag=data["tag"],
            path=path,
            architecture=data.get("architecture") or "unknown",
            capabilities=list(data.get("capabilities") or []),
            size_bytes=path.stat().st_size,
            parameter_size=data.get("parameter_size") or "unknown",
            context_length=int(data.get("context_length") or 0),
        )
