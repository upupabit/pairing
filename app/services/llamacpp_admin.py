"""Model administration for llama.cpp: pull and delete in the shared GGUF store (gguf_model_store), then rebuild
the router's preset and ask it to reload (`GET /models?reload=1`), so no restart is needed.

Local mode only: a remote llama-server's disk isn't reachable from here, so its models are managed on that host.
"""

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from app.database import AsyncSessionLocal
from app.schemas import LlamaCppServerConfig
from app.services import context_window_setting, llamacpp_pool, settings_service
from app.services.gguf_direct_puller import GgufDirectPuller
from app.services.gguf_model_store import GgufModelStore
from app.services.huggingface_client import HuggingFaceCatalogSearch
from app.services.llamacpp_errors import LlamaCppError
from app.services.llamacpp_models import LlamaCppCatalog, LlamaCppModelName, LlamaCppModelsFolder
from app.services.llamacpp_preset import LlamaCppPreset

logger = logging.getLogger("llama_chat")

_RELOAD_TIMEOUT = httpx.Timeout(30.0, connect=2.0)
# Preferred projector precisions when a repo offers several (llama.cpp's own -hf pick favours F16 too).
_PROJECTOR_PREFERENCE = ("f16", "bf16", "q8_0", "f32")
_REMOTE_HINT = "Models of a remote llama-server are managed on that host; switch to Local mode to pull or remove here."


async def models_folder() -> Path:
    async with AsyncSessionLocal() as db:
        config = await settings_service.get_llamacpp_server_config(db)
        matricxon_config = await settings_service.get_matricxon_server_config(db)
    return LlamaCppModelsFolder.resolve(config, matricxon_config)


async def default_models_folder() -> Path:
    """What a blank models_path resolves to: Matricxon's folder, or the fallback without Matricxon."""
    async with AsyncSessionLocal() as db:
        matricxon_config = await settings_service.get_matricxon_server_config(db)
    return LlamaCppModelsFolder.resolve(LlamaCppServerConfig(), matricxon_config)


async def store() -> GgufModelStore:
    return GgufModelStore(await models_folder())


async def sync_preset(reload: bool = True) -> None:
    """Rewrites the preset from the store and, if it changed and the router runs, asks it to reload. Also called on
    every local model listing, since Matricxon can change the shared store without llama.cpp knowing.
    """
    async with AsyncSessionLocal() as db:
        config = await settings_service.get_llamacpp_server_config(db)
        num_ctx = await context_window_setting.get_num_ctx(db)
    entries = LlamaCppCatalog(await store()).entries()
    changed = LlamaCppPreset(entries, num_ctx, config.num_parallel or 1).write()
    if changed and reload and llamacpp_pool.is_local():
        await _reload_router()


async def reload_if_unknown(error: str) -> bool:
    """For a local router's "model ... not found": the store may have changed outside llama.cpp (a model Matricxon
    pulled into the shared folder), so the preset is rebuilt. True when the caller should retry.
    """
    if "not found" not in error.lower() or not llamacpp_pool.is_local():
        return False
    logger.info("llama-server did not know a model (%s); rebuilding its model list.", error)
    await sync_preset()
    return True


async def _reload_router() -> None:
    try:
        async with httpx.AsyncClient(timeout=_RELOAD_TIMEOUT) as client:
            (await client.get(f"{llamacpp_pool.LOCAL_LLAMACPP_HOST}/models", params={"reload": 1})).raise_for_status()
    except httpx.HTTPError as exc:
        # Not running is fine: the preset is read at the next start.
        logger.info("llama-server did not reload its model list (%s); it applies at next start.", exc)


class LlamaCppDirectPuller(GgufDirectPuller):
    error_type = LlamaCppError

    def __init__(self, root: Path) -> None:
        self._root = root

    async def _destination(self, repo_id: str, filename: str) -> Path:
        return self._root / "hf.co" / repo_id / filename

    async def _infer_capabilities(self, repo_id: str, filename: str, architecture: str | None) -> list[str]:
        """Matricxon's pull-time rule (its CapabilityInferer), so the shared sidecar reads the same to Matricxon."""
        if architecture in (None, "clip"):
            return []
        capabilities = ["embedding" if architecture in ("bert", "nomic-bert") else "completion"]
        if any(marker in f"{repo_id}/{filename}".lower() for marker in ("thinking", "reasoning")):
            capabilities.append("thinking")
        return capabilities

    async def pull_stream(self, tag: str) -> AsyncIterator[dict]:
        """Like the base, plus the repo's vision projector when the model is not one (as Ollama paired it)."""
        repo_id, suffix = self._parse_tag(tag)
        yield {"status": "resolving manifest"}
        matched, context_length, files = await self._resolve(repo_id, suffix)
        async for progress in self._pull_file(tag, repo_id, matched, context_length):
            yield progress
        projector = self._projector_of(matched, files)
        if projector is not None:
            projector_tag = f"hf.co/{repo_id}:{Path(projector['filename']).stem}"
            async for progress in self._pull_file(projector_tag, repo_id, projector, context_length):
                yield progress
        yield {"status": "success"}

    @staticmethod
    def _projector_of(matched: dict, files: list[dict]) -> dict | None:
        if HuggingFaceCatalogSearch.is_projector_file(matched["filename"]):
            return None
        projectors = [f for f in files if HuggingFaceCatalogSearch.is_projector_file(f["filename"])]
        for precision in _PROJECTOR_PREFERENCE:
            for candidate in projectors:
                # The last name segment, so "bf16" never counts as "f16".
                if re.split(r"[-_.]", Path(candidate["filename"]).stem.lower())[-1] == precision:
                    return candidate
        return projectors[0] if projectors else None


async def pull_model_stream(tag: str) -> AsyncIterator[dict]:
    """Downloads `tag` (and its projector) into the shared store, then makes the router see it."""
    if not llamacpp_pool.is_local():
        raise LlamaCppError(_REMOTE_HINT)
    async for progress in LlamaCppDirectPuller(await models_folder()).pull_stream(tag):
        if progress.get("status") == "success":
            await sync_preset()
        yield progress


async def delete_model(tag: str) -> None:
    """Unloads, removes the file and sidecar, and drops it from the preset. Also removes it for Matricxon, which
    shares the store.
    """
    if not llamacpp_pool.is_local():
        raise LlamaCppError(_REMOTE_HINT)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as client:
            await client.post(
                f"{llamacpp_pool.LOCAL_LLAMACPP_HOST}/models/unload", json={"model": LlamaCppModelName.to_router(tag)}
            )
    except httpx.HTTPError:
        pass  # not running or not loaded
    if not (await store()).delete(tag):
        raise LlamaCppError(f"{tag} is not installed.")
    await sync_preset()
