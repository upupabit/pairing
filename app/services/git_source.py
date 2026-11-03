"""A git checkout as an update source: fetch, compare with upstream, fast-forward. With a chosen repository
(update_source.GitRemote) it fetches that one through its own `update-source` remote instead of the checkout's
upstream; `origin` and the tracked branch stay as they are."""

import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

from app.services.update_process import UpdateProcess
from app.services.update_source import REMOTE, GitRemote, explain_git_error

_PROGRESS = re.compile(r"^(Counting objects|Compressing objects|Receiving objects|Resolving deltas):\s+(\d+)%")
_MAX_CHANGES = 20
# Fetch GitHub over HTTPS even when the remote is SSH: no keys needed, and the proxy applies. Remotes stay as they are.
_HTTPS_FETCH = (
    "-c",
    "url.https://github.com/.insteadOf=git@github.com:",
    "-c",
    "url.https://github.com/.insteadOf=ssh://git@github.com/",
)


class GitSource:
    def __init__(
        self, path: Path, process: UpdateProcess, remote: GitRemote | None = None, token: str | None = None
    ) -> None:
        """`token`: for a private origin when there is no chosen repository (a chosen one carries its own)."""
        self.path = path
        self._process = process
        self._remote = remote
        self._origin_token = None if remote else token
        self._upstream = remote.ref if remote else "@{u}"
        if remote:
            process.env = {**process.env, **remote.git_env()}

    @staticmethod
    def usable(path: Path) -> bool:
        """git is on PATH and `path` is a checkout."""
        return shutil.which("git") is not None and (path / ".git").exists()

    async def _git(self, *args: str, timeout: float = 60.0) -> str:
        try:
            return await self._process.output(["git", *args], cwd=self.path, timeout=timeout)
        except RuntimeError as exc:
            raise RuntimeError(explain_git_error(str(exc))) from exc

    async def head(self) -> str:
        return await self._git("rev-parse", "--short", "HEAD")

    async def upstream(self) -> str:
        """Short sha of the tracked branch; RuntimeError if none is set."""
        return await self._git("rev-parse", "--short", self._upstream)

    async def fetch(self) -> None:
        await self._git(*await self._fetch_args("--quiet"), timeout=45.0)

    async def counts(self) -> tuple[int, int]:
        """(behind, ahead) relative to upstream."""
        out = await self._git("rev-list", "--left-right", "--count", f"{self._upstream}...HEAD")
        behind, ahead = out.split()
        return int(behind), int(ahead)

    async def pending_changes(self) -> list[str]:
        out = await self._git("log", "--oneline", f"-n{_MAX_CHANGES}", f"HEAD..{self._upstream}")
        return out.splitlines()

    async def changed_files(self, old: str, new: str) -> list[str]:
        return (await self._git("diff", "--name-only", old, new)).splitlines()

    async def fetch_stream(self) -> AsyncIterator[dict]:
        """git fetch with percent events; other lines as status."""
        try:
            async for line in self._process.stream(["git", *await self._fetch_args("--progress")], cwd=self.path):
                match = _PROGRESS.match(line)
                if match:
                    yield {"activity": match[1].lower(), "completed": int(match[2]), "total": 100, "unit": "percent"}
                else:
                    yield {"status": line}
        except RuntimeError as exc:
            raise RuntimeError(explain_git_error(str(exc))) from exc

    async def fast_forward_stream(self) -> AsyncIterator[str]:
        async for line in self._process.stream(["git", "merge", "--ff-only", self._upstream], cwd=self.path):
            yield line

    async def _authorize_origin(self) -> None:
        """The token as a header for the origin's host, once; an SSH origin (not GitHub's) uses the machine's key."""
        if not self._origin_token:
            return
        url = await self._git(*_HTTPS_FETCH, "ls-remote", "--get-url", "origin")
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.hostname:
            self._process.env = {
                **self._process.env,
                **GitRemote.header_env(f"https://{parsed.hostname}/", self._origin_token),
            }
        self._origin_token = None

    async def _fetch_args(self, *flags: str) -> list[str]:
        """The fetch command: the upstream over HTTPS, or the chosen repository's branch into its own ref."""
        if not self._remote:
            await self._authorize_origin()
            return [*_HTTPS_FETCH, "fetch", *flags]
        try:
            await self._git("remote", "set-url", REMOTE, self._remote.url)
        except RuntimeError:
            await self._git("remote", "add", "--no-fetch", REMOTE, self._remote.url)
        branch = self._remote.branch
        return ["fetch", *flags, REMOTE, f"+{branch}:{self._remote.ref}"]
