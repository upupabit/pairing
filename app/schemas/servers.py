"""Cluster > Servers: the pAIring servers sharing this database and "Update all"."""

from pydantic import BaseModel, Field


class ServerOut(BaseModel):
    server_id: str
    # The machine it runs on: a primary and its local instances share it (the list shows them as one server).
    machine: str = ""
    version: str
    git_commit: str | None = None
    is_primary: bool
    online: bool
    leader: bool
    seconds_since_seen: int
    this_server: bool
    update_state: str | None = None
    # While it updates: {step, total_steps, label, percent}, from rolling_update.progress().
    update_progress: dict | None = None


class RolloutOut(BaseModel):
    id: str
    status: str  # running, finished, stopped, cancelled
    queue: list[str] = Field(default_factory=list)
    current: str | None = None
    results: dict[str, str] = Field(default_factory=dict)
    message: str | None = None
    order: list[str] = Field(default_factory=list)  # every server, in update order
    started_at: int | None = None  # database epoch seconds, like `server_time`
    finished_at: int | None = None
    current_since: int | None = None
    durations: dict[str, int] = Field(default_factory=dict)  # seconds each finished server took


class ServersOverview(BaseModel):
    servers: list[ServerOut]
    rollout: RolloutOut | None = None
    # False on SQLite: one machine only, so no "Update all".
    shared_database: bool = True
    server_time: int | None = None  # the database clock, for the rollout's elapsed times


class ServerCheck(BaseModel):
    """One line of Cluster > Servers' checklist; `ok` is None while it can't tell yet."""

    id: str
    ok: bool | None
    title: str
    detail: str = ""
    fix: str = ""


class FolderState(BaseModel):
    path: str
    shared_fs: bool  # on a network filesystem (NFS, SMB...), from the mount table
    same: bool | None = None  # holds the leader's marker: the same folder as the leader's


class ServerFolders(BaseModel):
    server_id: str
    folders: dict[str, FolderState]


class ServerChecks(BaseModel):
    shared_database: bool
    checks: list[ServerCheck]
    folders: list[ServerFolders]


class ThisServerFolder(BaseModel):
    running: str  # what this process uses now
    saved: str | None = None  # in .env, applied at the next restart


class ThisServerSettings(BaseModel):
    """The server the admin is on: its folders and whether SECRET_KEY is set (the key itself is never shown)."""

    server_id: str
    folders: dict[str, ThisServerFolder]
    secret_set: bool
    secret_saved: bool  # a SECRET_KEY is in .env (may be newer than the running one)
    restart_needed: bool
    can_restart: bool
    restart_hint: str


class ThisServerUpdate(BaseModel):
    """Only the fields given change; a folder must be an absolute path."""

    folders: dict[str, str] = Field(default_factory=dict)
    secret_key: str | None = Field(default=None, min_length=32, max_length=256)
