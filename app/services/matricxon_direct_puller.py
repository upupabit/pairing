"""Downloads a Matricxon model directly from Hugging Face instead of proxying through Matricxon's `/api/pull`
(matricxon_admin's other path, still used for remote hosts), which was reported as "slowing it very much"
on a local install. The download itself is gguf_direct_puller's; this picks Matricxon's models folder and asks
Matricxon's `/api/infer-capabilities` for the sidecar, so its rules aren't duplicated here.

Local Matricxon only (matricxon_admin decides): writing to disk needs a shared filesystem.
"""

from pathlib import Path

import httpx

from app.database import AsyncSessionLocal
from app.schemas import MatricxonServerConfig
from app.services import matricxon_pool, matricxon_process, settings_service
from app.services.gguf_direct_puller import GgufDirectPuller
from app.services.matricxon_client import MatricxonError


class MatricxonDirectPuller(GgufDirectPuller):
    error_type = MatricxonError

    @staticmethod
    async def _get_config() -> MatricxonServerConfig:
        """Own session: the pull chain has no request `db`."""
        async with AsyncSessionLocal() as db:
            return await settings_service.get_matricxon_server_config(db)

    async def _destination(self, repo_id: str, filename: str) -> Path:
        return self._resolve_dest(repo_id, filename, await self._get_config())

    @staticmethod
    def _resolve_dest(repo_id: str, filename: str, config: MatricxonServerConfig) -> Path:
        root = MatricxonDirectPuller.models_root(config)
        if root is None:
            raise MatricxonError("Matricxon's local install couldn't be found to write the pulled model into.")
        return root / "hf.co" / repo_id / filename

    @staticmethod
    def models_root(config: MatricxonServerConfig) -> Path | None:
        """Matricxon's models folder: the override, else `data/models` in its checkout; None if neither exists."""
        if config.models_path:
            return Path(config.models_path)
        project_dir = matricxon_process.resolve_project_dir(config.project_dir)
        return project_dir / "data" / "models" if project_dir is not None else None

    async def _infer_capabilities(self, repo_id: str, filename: str, architecture: str | None) -> list[str]:
        """Matricxon's `/api/infer-capabilities`. An unknown `architecture` (probe failed) has none."""
        if architecture is None:
            return []
        host = matricxon_pool.pick_host()
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            try:
                resp = await client.post(
                    f"{host}/api/infer-capabilities",
                    json={"repo_id": repo_id, "filename": filename, "architecture": architecture},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise MatricxonError(f"Could not reach Matricxon at {host}: {self._describe(exc)}") from exc
        return resp.json()["capabilities"]
