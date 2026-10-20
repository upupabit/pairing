"""Downloads a `hf.co/<repo>:<file>` GGUF straight from Hugging Face into a shared models folder, in the layout
Matricxon reads (`<root>/hf.co/<repo>/<file>.gguf` plus a `<stem>.gguf.json` sidecar). Matricxon and llama.cpp
use the same folder, so a model pulled under one engine is installed for both (gguf_model_store).

Subclasses pick the folder, the error type and the sidecar's `capabilities` (MatricxonDirectPuller,
LlamaCppDirectPuller).

Accepted limitations:
  - The sidecar's `context_length` comes from the repo-level `gguf` block (HuggingFaceCatalogSearch.repo_files),
    not a per-file read like `architecture`. Cosmetic.
  - Settings > System's outbound proxy (http_proxy_service) isn't honored, as before this was shared.
"""

import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from app.services import gguf_probe
from app.services.download_coordinator import get_download_coordinator
from app.services.huggingface_client import HuggingFaceCatalogSearch

_TIMEOUT = httpx.Timeout(None, connect=10.0)
_CHUNK_SIZE = 1024 * 1024
# A progress line per 8MB, not per 1MB chunk.
_PROGRESS_THROTTLE_BYTES = 8 * 1024 * 1024


class GgufDirectPuller:
    error_type: type[Exception] = RuntimeError

    async def _destination(self, repo_id: str, filename: str) -> Path:
        """Where `filename` is written; subclasses resolve their models folder."""
        raise NotImplementedError

    async def _infer_capabilities(self, repo_id: str, filename: str, architecture: str | None) -> list[str]:
        """The sidecar's `capabilities` (Matricxon's pull-time view)."""
        raise NotImplementedError

    async def pull_stream(self, tag: str) -> AsyncIterator[dict]:
        """Yields NDJSON-style pull progress (`status`, plus `completed`/`total` while downloading); raises
        `error_type` on any failure, so inference_client's wrapping into InferenceError still works.
        """
        repo_id, suffix = self._parse_tag(tag)
        yield {"status": "resolving manifest"}
        matched, context_length, _files = await self._resolve(repo_id, suffix)
        async for progress in self._pull_file(tag, repo_id, matched, context_length):
            yield progress
        yield {"status": "success"}

    async def _pull_file(
        self, tag: str, repo_id: str, matched: dict, context_length: int | None
    ) -> AsyncIterator[dict]:
        filename = matched["filename"]
        dest = await self._destination(repo_id, filename)
        partial_path = dest.with_suffix(dest.suffix + ".partial")
        async with get_download_coordinator().guard(dest):
            if dest.exists():
                size = dest.stat().st_size
                yield {"status": "already downloaded", "completed": size, "total": size}
            else:
                async for progress in self._download(repo_id, matched, dest, partial_path):
                    yield progress
        architecture, parameter_count = await self._probe(repo_id, filename)
        capabilities = await self._infer_capabilities(repo_id, filename, architecture)
        self._write_sidecar(dest, tag, architecture, parameter_count, capabilities, context_length)

    @classmethod
    def _parse_tag(cls, tag: str) -> tuple[str, str]:
        """`tag` is `hf.co/<repo_id>:<suffix>`; a curated suffix may be short (e.g. "Q8_0"), see _match."""
        if not tag.startswith("hf.co/") or ":" not in tag:
            raise cls.error_type(f'"{tag}" is not an hf.co/<repo>:<file> tag — cannot pull it directly.')
        repo_id, _, suffix = tag.removeprefix("hf.co/").partition(":")
        return repo_id, suffix

    @classmethod
    async def _resolve(cls, repo_id: str, suffix: str) -> tuple[dict, int | None, list[dict]]:
        """Re-fetches the real repo listing, never trusting a caller's size/sha256. Returns the matched file, the
        repo-level context_length and every file (for a paired projector).
        """
        try:
            repo = await HuggingFaceCatalogSearch.repo_files(repo_id, proxy_url=None)
        except Exception as exc:  # noqa: BLE001 - HuggingFaceLookupError or a raw httpx failure either way
            raise cls.error_type(f'Could not resolve "{repo_id}" on Hugging Face: {cls._describe(exc)}') from exc
        return cls._match(suffix, repo["files"]), repo["context_length"], repo["files"]

    @staticmethod
    def _describe(exc: Exception) -> str:
        """Some httpx exceptions stringify to ""; falls back to the type name plus the request URL."""
        message = str(exc)
        if message:
            return message
        request = getattr(exc, "request", None)
        if request is not None:
            return f"{type(exc).__name__} for {request.url}"
        return type(exc).__name__

    @classmethod
    def _match(cls, suffix: str, files: list[dict]) -> dict:
        """Exact stem first, then a unique substring, so a short curated suffix ("Q8_0") resolves too."""
        suffix_lower = suffix.lower()
        exact = [f for f in files if Path(f["filename"]).stem.lower() == suffix_lower]
        if len(exact) == 1:
            return exact[0]
        substring = [f for f in files if suffix_lower in f["filename"].lower()]
        if len(substring) == 1:
            return substring[0]
        candidates = ", ".join(f["filename"] for f in files)
        if not exact and not substring:
            raise cls.error_type(f'No .gguf file matching "{suffix}" — available: {candidates}')
        raise cls.error_type(f'Ambiguous suffix "{suffix}", matches multiple files — available: {candidates}')

    async def _download(self, repo_id: str, matched: dict, dest: Path, partial_path: Path) -> AsyncIterator[dict]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = matched["size_bytes"]
        digest = hashlib.sha256()
        completed = 0
        last_yield = 0
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                url = f"https://huggingface.co/{repo_id}/resolve/main/{matched['filename']}"
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with partial_path.open("wb") as f:
                        async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                            f.write(chunk)
                            digest.update(chunk)
                            completed += len(chunk)
                            if completed - last_yield >= _PROGRESS_THROTTLE_BYTES:
                                last_yield = completed
                                yield {
                                    "status": f"pulling {matched['filename']}",
                                    "completed": completed,
                                    "total": total,
                                }
        except httpx.HTTPError as exc:
            partial_path.unlink(missing_ok=True)
            raise self.error_type(f"download of {matched['filename']!r} failed: {self._describe(exc)}") from exc
        except BaseException:
            # Also on cancellation: a client leaving mid-download must not leave a half-written file.
            partial_path.unlink(missing_ok=True)
            raise

        if matched["sha256"] is not None and digest.hexdigest() != matched["sha256"]:
            partial_path.unlink(missing_ok=True)
            raise self.error_type(f"downloaded file failed sha256 verification: {matched['filename']!r}")

        partial_path.rename(dest)
        yield {"status": f"pulling {matched['filename']}", "completed": completed, "total": total}

    @staticmethod
    async def _probe(repo_id: str, filename: str) -> tuple[str | None, int | None]:
        probed = await gguf_probe.probe_metadata(repo_id, filename, proxy_url=None)
        if probed is None:
            return None, None
        return probed["architecture"], probed["parameter_count"]

    @staticmethod
    def _format_parameter_size(parameter_count: int | None) -> str:
        """Same as Matricxon's pull job formatter."""
        if parameter_count is None:
            return "unknown"
        if parameter_count >= 1e9:
            return f"{parameter_count / 1e9:.1f}B"
        return f"{parameter_count / 1e6:.0f}M"

    def _write_sidecar(
        self,
        gguf_path: Path,
        tag: str,
        architecture: str | None,
        parameter_count: int | None,
        capabilities: list[str],
        context_length: int | None,
    ) -> None:
        """Exactly Matricxon's `InstalledModel` fields: it loads sidecars with `InstalledModel(**data)`, so an
        extra key would hide the model there.
        """
        architecture = architecture or "unknown"
        installed = {
            "tag": tag,
            "path": str(gguf_path),
            "architecture": architecture,
            "capabilities": capabilities,
            "size_bytes": gguf_path.stat().st_size,
            "family": architecture,
            "parameter_size": self._format_parameter_size(parameter_count),
            "context_length": context_length or 0,
        }
        sidecar_path = gguf_path.parent / f"{gguf_path.stem}.gguf.json"
        sidecar_path.write_text(json.dumps(installed))
