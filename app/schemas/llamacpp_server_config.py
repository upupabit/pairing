"""Schemas for the llama.cpp admin (Settings > Inference engines). Supervisor: services/llamacpp_process.py
(`llama-server` in router mode); HTTP half: llamacpp_pool.py (local: managed process; remote: `remote_hosts`,
load-balanced), which this config only chooses between.
"""

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import MAX_REMOTE_HOSTS, ServerMode


class LlamaCppServerConfig(BaseModel):
    """Admin-configured. Local-mode fields are optional: None = llama-server's own default."""

    mode: ServerMode = "local"
    remote_hosts: list[str] = Field(default_factory=list, max_length=MAX_REMOTE_HOSTS)
    # A llama-server installed elsewhere; checked before PATH and the managed install. None = auto-detect.
    binary_path: str | None = None
    # The GGUF models folder. None = share Matricxon's folder (llamacpp_models_dir), so each model is stored once.
    models_path: str | None = None
    # Local mode only, ignored in "remote"; passed to llama-server (llamacpp_process.build_argv):
    num_parallel: int | None = Field(None, ge=1, le=16)  # --parallel
    max_loaded_models: int | None = Field(None, ge=0, le=16)  # --models-max (0 = unlimited)
    # --sleep-idle-seconds: frees a model's memory after this much idle time, like Ollama's 5 minute keep-alive.
    idle_unload_seconds: int | None = Field(300, ge=0)
    gpu_layers: int | None = Field(None, ge=-1)  # --n-gpu-layers; None = llama-server's default
    # Anything else, as a command line fragment (e.g. "--threads 8").
    extra_args: str | None = None
    # Overrides for llamacpp_installer. None = app.config.LLAMACPP_GITHUB_REPO/LLAMACPP_PINNED_VERSION.
    install_repo: str | None = None
    install_version: str | None = None
    # Release build: None = plain CPU; e.g. "vulkan" or "cuda-12.8" for llama-<ver>-bin-ubuntu-<variant>-x64.tar.gz.
    install_variant: str | None = None

    @field_validator("install_variant", "extra_args", "binary_path", "models_path", "install_repo", "install_version")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def _fall_back_to_local_when_remote_has_no_hosts(self) -> "LlamaCppServerConfig":
        """ "Remote" with no hosts is never useful and could leave an admin stuck; also self-heals a saved row."""
        if self.mode == "remote" and not self.remote_hosts:
            self.mode = "local"
        return self


class LlamaCppAutoDetectedPath(BaseModel):
    """What a blank binary_path/models_path resolves to; shown as the fields' placeholders."""

    path: str | None = None
    models_path: str | None = None


class LlamaCppServerStatus(BaseModel):
    """GET.../status, same shape as SdCppStatus. `pid`/`healthy` are None when not running."""

    running: bool
    installed: bool = False
    pid: int | None = None
    healthy: bool | None = None
