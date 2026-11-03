"""What each server reports in its heartbeat for the multi-server checks (servers_check.py): a fingerprint of
SECRET_KEY (never the key) and its 4 folders that must be shared.

A matching path alone can be a local disk on each machine, so the leader writes a marker file into each folder
with a fresh id every MARKER_SECONDS (kept in app_settings, plus the previous one); a server whose folder holds
the current or previous id reads the same folder.
"""

import hashlib
import hmac
import secrets
import socket
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ATTACHMENTS_DIR, AVATARS_DIR, IMAGES_DIR, KNOWLEDGE_DIR, SECRET_KEY, SECRET_KEY_IS_SET
from app.models import SYSTEM_OWNER_ID, AppSetting
from app.services.db_clock import db_epoch
from app.services.fs_probe import FilesystemProbe

SHARED_FOLDERS = {
    "KNOWLEDGE_DIR": KNOWLEDGE_DIR,
    "ATTACHMENTS_DIR": ATTACHMENTS_DIR,
    "AVATARS_DIR": AVATARS_DIR,
    "IMAGES_DIR": IMAGES_DIR,
}
MARKER_FILE = ".pairing_share_id"  # no document extension: the knowledge sync ignores it
MARKERS_KEY = "shared_folder_markers"


def secret_fingerprint(key: str = SECRET_KEY) -> str:
    """Equal on two servers exactly when their SECRET_KEY is; reveals nothing usable about the key."""
    return hmac.new(key.encode(), b"pairing-secret-fingerprint", hashlib.sha256).hexdigest()[:12]


class ServerFacts:
    MARKER_SECONDS = 300

    def __init__(self, folders: dict[str, Path] = SHARED_FOLDERS, probe: FilesystemProbe | None = None) -> None:
        self._folders = folders
        self._probe = probe or FilesystemProbe()

    def report(self) -> dict:
        return {
            "machine": socket.gethostname(),  # groups a server's local instances in the list
            "secret": secret_fingerprint(),
            "secret_set": SECRET_KEY_IS_SET,
            "folders": {
                name: {"path": str(path), "shared": self._shared(path), "marker": self._read_marker(path)}
                for name, path in self._folders.items()
            },
        }

    async def markers(self, db: AsyncSession) -> dict:
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, MARKERS_KEY))
        return dict(row.value) if row else {}

    async def refresh_markers(self, db: AsyncSession) -> None:
        """Leader only: a fresh id in every folder once the last one is MARKER_SECONDS old."""
        now = await db_epoch(db)
        current = await self.markers(db)
        if current and now - current.get("at", 0) < self.MARKER_SECONDS:
            return
        value = {"at": now, "ids": {}, "previous": current.get("ids", {})}
        for name, path in self._folders.items():
            marker = secrets.token_hex(8)
            try:
                path.mkdir(parents=True, exist_ok=True)
                (path / MARKER_FILE).write_text(marker)
                value["ids"][name] = marker
            except OSError:
                pass  # reported as not shared: the leader can't write there
        row = await db.get(AppSetting, (SYSTEM_OWNER_ID, MARKERS_KEY))
        if row is None:
            db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=MARKERS_KEY, value=value))
        else:
            row.value = value
        await db.commit()

    def _shared(self, path: Path) -> bool:
        try:
            return self._probe.is_shared(path)
        except OSError:
            return False

    @staticmethod
    def _read_marker(path: Path) -> str | None:
        try:
            return (path / MARKER_FILE).read_text().strip() or None
        except OSError:
            return None


server_facts = ServerFacts()
