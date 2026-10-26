"""What llama.cpp has installed: the shared GGUF store (gguf_model_store) seen through llama.cpp's eyes.

- LlamaCppModelName: llama-server's router rewrites a preset name shaped like `<repo>:<tag>` (checked on b11443:
  `hf.co/org/repo:Model-Q4_K_M` was listed as `hf.co/org/repo:Q4_K_M`), so the router knows each model by its tag
  with the first ":" as "@", which it keeps as is.
- LlamaCppModelsFolder: where the store is (the admin's override, else Matricxon's folder, so both share files).
- LlamaCppCatalog: installed models in the list shape the catalog code reads (name/size/details/capabilities),
  with capabilities inferred from each file's header, since the store's sidecar holds Matricxon's view.
"""

from pathlib import Path

from app.config import BASE_DIR
from app.schemas import LlamaCppServerConfig, MatricxonServerConfig
from app.services.gguf_local_metadata import GgufLocalMetadata
from app.services.gguf_model_store import GgufModelStore, StoredModel
from app.services.matricxon_direct_puller import MatricxonDirectPuller

# Used only when no Matricxon checkout or override exists to share with.
FALLBACK_MODELS_DIR = BASE_DIR / "models"

# Encoder architectures llama.cpp runs as embedding models even if a file lacks `<arch>.pooling_type`.
_EMBEDDING_ARCHITECTURES = frozenset(
    {"bert", "nomic-bert", "nomic-bert-moe", "jina-bert-v2", "modern-bert", "neo-bert"}
)
_RANK_POOLING = 4


class LlamaCppModelName:
    @staticmethod
    def to_router(tag: str) -> str:
        return tag.replace(":", "@", 1)

    @staticmethod
    def from_router(name: str) -> str:
        return name.replace("@", ":", 1) if name.startswith("hf.co/") else name


class LlamaCppModelsFolder:
    @staticmethod
    def resolve(config: LlamaCppServerConfig, matricxon_config: MatricxonServerConfig) -> Path:
        if config.models_path:
            return Path(config.models_path).expanduser()
        return MatricxonDirectPuller.models_root(matricxon_config) or FALLBACK_MODELS_DIR


class LlamaCppCapabilities:
    """Capabilities llama.cpp has for one installed file. Cached per (path, size, mtime): reading a header is a
    disk read, and the list is built on every Settings page load.
    """

    _cache: dict[tuple[str, int, float], tuple[str, ...]] = {}

    @classmethod
    def of(cls, model: StoredModel, has_projector: bool) -> list[str]:
        stat = model.path.stat()
        key = (str(model.path), stat.st_size, stat.st_mtime)
        if key not in cls._cache:
            cls._cache[key] = tuple(cls._infer(model, GgufLocalMetadata.read(model.path)))
        capabilities = list(cls._cache[key])
        if has_projector and "completion" in capabilities:
            capabilities.append("vision")
        return capabilities

    @staticmethod
    def _infer(model: StoredModel, meta: GgufLocalMetadata) -> list[str]:
        architecture = meta.architecture or model.architecture
        if model.is_projector or architecture == "clip":
            return []
        if meta.pooling_type == _RANK_POOLING:
            return ["rerank"]
        if meta.pooling_type or architecture in _EMBEDDING_ARCHITECTURES:
            return ["embedding"]
        capabilities = ["completion"]
        template = meta.chat_template or ""
        if "tool" in template:
            capabilities.append("tools")
        if "think" in template:
            capabilities.append("thinking")
        # The switch used before the reply prompt (Gemma 4: in the system turn): changing Thinking on a live chat
        # re-reads it once. Matricxon checks this by rendering; here the template text has to do.
        switch, reply_prompt = template.find("enable_thinking"), template.find("add_generation_prompt")
        if switch != -1 and (reply_prompt == -1 or switch < reply_prompt):
            capabilities.append("thinking_rereads")
        return capabilities


class LlamaCppCatalog:
    def __init__(self, store: GgufModelStore) -> None:
        self._store = store

    def entries(self) -> list[tuple[StoredModel, StoredModel | None, list[str]]]:
        """(model, its projector, capabilities) per installed file, projectors included."""
        models = self._store.models()
        result = []
        for model in models:
            projector = self._store.projector_for(model, models)
            result.append((model, projector, LlamaCppCapabilities.of(model, projector is not None)))
        return result

    def list_models(self) -> list[dict]:
        """The `/api/tags`-style list Matricxon and the catalog code use, so one catalog builder serves both."""
        return [
            {
                "name": model.tag,
                "model": model.tag,
                "size": model.size_bytes,
                "capabilities": capabilities,
                "details": {
                    "family": model.architecture,
                    "parameter_size": model.parameter_size,
                    "context_length": model.context_length,
                },
            }
            for model, _projector, capabilities in self.entries()
        ]
