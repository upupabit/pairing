"""Settings > Matricxon > API key, and the Cluster page's API key (app/routers/matricxon_api_key_admin.py). The key
itself never goes back to the browser: only whether one is set."""

from pydantic import BaseModel, Field


class MatricxonApiKeyUpdate(BaseModel):
    # "" removes the key.
    key: str = Field(default="", max_length=200, pattern=r"^[^\s,]*$")


class MatricxonApiKeyState(BaseModel):
    set: bool
    # Cluster mode on: the key is set on the Cluster page (for every node), not on the Inference engines panel.
    cluster: bool = False
