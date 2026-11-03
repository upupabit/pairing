"""Cluster > Servers > This server: its 4 shared folders and SECRET_KEY, saved into its own .env (every
server has its own, so this never changes the others). Applied at the next restart; the key is never shown."""

from pathlib import Path

from app.config import SECRET_KEY_IS_SET, SERVER_ID
from app.schemas.servers import ThisServerFolder, ThisServerSettings, ThisServerUpdate
from app.services import env_file
from app.services.server_facts import SHARED_FOLDERS
from app.services.update_targets import PairingUpdate


class ThisServerSettingsError(ValueError):
    """Shown to the admin, e.g. a relative folder path."""


class ThisServerSettingsService:
    def __init__(self, env_path: Path | None = None, folders: dict[str, Path] = SHARED_FOLDERS) -> None:
        self._env_path = env_path
        self._folders = folders
        self._restart_needed = False

    def current(self) -> ThisServerSettings:
        restart = PairingUpdate().restart_info()
        return ThisServerSettings(
            server_id=SERVER_ID,
            folders={
                name: ThisServerFolder(running=str(path), saved=env_file.read_env_value(name, self._env_path))
                for name, path in self._folders.items()
            },
            secret_set=SECRET_KEY_IS_SET,
            secret_saved=bool(env_file.read_env_value("SECRET_KEY", self._env_path)),
            restart_needed=self._restart_needed,
            can_restart=restart.can_restart,
            restart_hint=restart.hint,
        )

    def save(self, update: ThisServerUpdate) -> ThisServerSettings:
        values: dict[str, str | None] = {}
        for name, raw in update.folders.items():
            if name not in self._folders:
                raise ThisServerSettingsError(f"Unknown folder setting: {name}.")
            path = Path(raw.strip())
            if not path.is_absolute():
                raise ThisServerSettingsError(f"{name} must be an absolute path, e.g. /mnt/pairing/{name.lower()}.")
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ThisServerSettingsError(f"{name}: can't use {path} ({exc.strerror}).") from exc
            values[name] = str(path)
        if update.secret_key:
            if any(c.isspace() for c in update.secret_key):
                raise ThisServerSettingsError("SECRET_KEY can't contain spaces.")
            values["SECRET_KEY"] = update.secret_key
        if values:
            env_file.write_env_values(values, self._env_path)
            self._restart_needed = True
        return self.current()


this_server_settings = ThisServerSettingsService()
