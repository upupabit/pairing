"""Downloads and installs llama.cpp's official prebuilt release from GitHub: the "local" auto-install behind
Settings > Inference engines' Install. Never "latest": the pinned app.config.LLAMACPP_PINNED_VERSION unless the
admin overrides it, for predictable reinstalls.

Asset shape (checked against b11443): `llama-<ver>-bin-ubuntu-<variant-><arch>.tar.gz` holding one `llama-<ver>/`
folder with `llama-server` and its shared libraries side by side, extracted flat into external/llama.cpp/.
"""

import logging
import platform
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from app.config import EXTERNAL_DIR, LLAMACPP_GITHUB_REPO, LLAMACPP_PINNED_VERSION
from app.hardware import local_install_supported
from app.services.llamacpp_process import MANAGED_BINARY

logger = logging.getLogger("llama_chat")

_DOWNLOAD_TIMEOUT = httpx.Timeout(None, connect=10.0)
# Every event carries step/total_steps/step_label (rendered as "Step X of Y" by settings.js installServer).
_TOTAL_STEPS = 2


class LlamaCppInstaller:
    def __init__(self, repo: str | None = None, version: str | None = None, variant: str | None = None) -> None:
        self._repo = repo or LLAMACPP_GITHUB_REPO
        self._version = version or LLAMACPP_PINNED_VERSION
        self._variant = variant

    @staticmethod
    def install_dir() -> Path:
        return EXTERNAL_DIR / "llama.cpp"

    @staticmethod
    def _arch_name() -> str:
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            return "x64"
        if machine in ("aarch64", "arm64"):
            return "arm64"
        raise RuntimeError(f"No llama.cpp release asset for this machine's architecture ({machine}).")

    def asset_url(self) -> str:
        build = f"{self._variant}-{self._arch_name()}" if self._variant else self._arch_name()
        name = f"llama-{self._version}-bin-ubuntu-{build}.tar.gz"
        return f"https://github.com/{self._repo}/releases/download/{self._version}/{name}"

    async def install_stream(self, proxy_url: str | None = None) -> AsyncIterator[dict]:
        """Streams the asset to disk, extracts it and yields progress ({"status"...}, then {"done": True} or
        {"error": ...}), relayed as SSE by routers/llamacpp_admin.py.
        """
        if not local_install_supported():
            yield {
                "error": (
                    f"Auto-install isn't available on this OS ({platform.system()}): the release asset is Linux-only. "
                    'Install llama.cpp yourself and use "Enter its path manually", or use Remote mode.'
                )
            }
            return
        if shutil.which("tar") is None:
            yield {"error": "'tar' was not found on PATH — required to extract the downloaded archive."}
            return
        try:
            url = self.asset_url()
        except RuntimeError as exc:
            yield {"error": str(exc)}
            return
        target = self.install_dir()
        target.mkdir(parents=True, exist_ok=True)
        archive = target / "llama.cpp.tar.gz"
        async for event in self._download(url, archive, proxy_url):
            yield event
            if "error" in event:
                return
        yield {"step": 2, "total_steps": _TOTAL_STEPS, "step_label": "Extracting", "status": "Extracting..."}
        result = subprocess.run(
            ["tar", "-xzf", str(archive), "-C", str(target), "--strip-components=1"],
            capture_output=True,
            text=True,
            check=False,
        )
        archive.unlink(missing_ok=True)
        if result.returncode != 0:
            yield {"error": f"Failed to extract the downloaded archive: {result.stderr.strip() or 'unknown tar error'}"}
            return
        if not MANAGED_BINARY.exists():
            yield {"error": "Extraction finished but llama-server wasn't found where expected."}
            return
        MANAGED_BINARY.chmod(0o755)
        logger.info("Installed llama.cpp %s to %s", self._version, target)
        yield {"done": True, "step": _TOTAL_STEPS, "total_steps": _TOTAL_STEPS, "binary_path": str(MANAGED_BINARY)}

    async def _download(self, url: str, archive: Path, proxy_url: str | None) -> AsyncIterator[dict]:
        meta = {"step": 1, "total_steps": _TOTAL_STEPS, "step_label": "Downloading"}
        yield {**meta, "status": f"Downloading llama.cpp {self._version}..."}
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True, proxy=proxy_url) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0)) or None
                    completed, last_pct = 0, -1
                    with open(archive, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
                            completed += len(chunk)
                            # Only on whole-percent changes: per-chunk events slowed the download itself.
                            if total and completed * 100 // total != last_pct:
                                last_pct = completed * 100 // total
                                yield {**meta, "status": "Downloading", "completed": completed, "total": total}
        except httpx.HTTPError as exc:
            archive.unlink(missing_ok=True)
            yield {"error": f"Could not download llama.cpp from {url}: {exc}"}
