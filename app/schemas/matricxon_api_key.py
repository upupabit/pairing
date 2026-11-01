"""Settings > Matricxon > API key (app/routers/matricxon_api_key_admin.py). The key itself never goes back to the
browser: only whether one is set."""

from pydantic import BaseModel, Field


class MatricxonApiKeyUpdate(BaseModel):
    # "" removes the key.
    key: str = Field(default="", max_length=200, pattern=r"^[^\s,]*$")


class MatricxonApiKeyState(BaseModel):
    set: bool
    # Local mode: the key is written to Matricxon's .env, so the local server enforces it after a restart.
    local: bool
    # A local Matricxon is running with the old setting: it needs a restart to apply the change.
    restart_needed: bool = False
