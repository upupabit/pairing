"""Admin settings > Update: what each updatable component reports."""

from typing import Literal

from pydantic import BaseModel, Field

UpdateMethod = Literal["git", "download"]
RestartMode = Literal["script", "systemd", "docker", "manual"]


class SourceUpdateStatus(BaseModel):
    name: str
    path: str | None = None
    # False when this install can't be updated from here; `note` says why.
    available: bool = False
    method: UpdateMethod | None = None
    current: str | None = None
    latest: str | None = None
    # None when unknown (e.g. a download install with no recorded version).
    update_available: bool | None = None
    behind: int | None = None
    changes: list[str] = Field(default_factory=list)
    note: str | None = None
    # The chosen repository ("url · branch"); None when it updates as installed.
    source: str | None = None


class PairingRestartInfo(BaseModel):
    mode: RestartMode
    can_restart: bool
    hint: str


class UpdateOverview(BaseModel):
    pairing: SourceUpdateStatus
    # None when Matricxon isn't installed locally.
    matricxon: SourceUpdateStatus | None = None
    restart: PairingRestartInfo


class UpdateSourceOut(BaseModel):
    """Where one product updates from (services/update_source.py). The token itself is never sent back."""

    product: str
    repo: str | None = None  # None: as installed
    branch: str | None = None
    has_token: bool = False
    default_repo: str
    default_branch: str


class UpdateSourceIn(BaseModel):
    repo: str | None = None  # empty: back to as installed (the token stays; clear_token removes it)
    branch: str | None = None
    token: str | None = None  # empty: keep the saved one
    clear_token: bool = False


class UpdateTokenIn(BaseModel):
    token: str | None = None  # None or empty: remove it
