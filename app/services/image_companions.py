"""Extra files a split image model needs beside its diffusion weights (text encoder, VAE), fetched with the
model and passed to sd-server automatically (no typing --llm/--vae). They live in a `_companions` folder next
to the model. Add a recipe to RECIPES for another model family.
"""

import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from app.services.hf_download import stream_file

FOLDER = "_companions"


@dataclass(frozen=True)
class Companion:
    flag: str
    repo: str
    filename: str
    label: str
    size_gb: float

    @property
    def local_name(self) -> str:
        return self.filename.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"


_FLUX1_VAE = Companion("--vae", "Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors", "FLUX VAE", 0.34)
_FLUX2_VAE = Companion("--vae", "Comfy-Org/flux2-dev", "split_files/vae/flux2-vae.safetensors", "FLUX.2 VAE", 0.34)
_CLIP_L = Companion("--clip_l", "comfyanonymous/flux_text_encoders", "clip_l.safetensors", "CLIP-L text encoder", 0.25)
_T5XXL = Companion(
    "--t5xxl", "comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn.safetensors", "T5-XXL text encoder", 4.9
)


@dataclass(frozen=True)
class Recipe:
    """Companions for model files whose name contains one of `keys` and none of `exclude`."""

    keys: tuple[str, ...]
    files: tuple[Companion, ...]
    exclude: tuple[str, ...] = ()

    def matches(self, name: str) -> bool:
        return any(k in name for k in self.keys) and not any(x in name for x in self.exclude)


# Files and flags as in stable-diffusion.cpp's docs, from ungated repos (the official VAEs are gated).
RECIPES: tuple[Recipe, ...] = (
    Recipe(
        ("z_image", "z-image"),
        (
            Companion(
                "--llm",
                "unsloth/Qwen3-4B-Instruct-2507-GGUF",
                "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
                "Qwen3-4B text encoder",
                2.5,
            ),
            _FLUX1_VAE,
        ),
    ),
    Recipe(
        ("klein-4b", "klein_4b", "klein-base-4b", "klein_base_4b"),
        (Companion("--llm", "unsloth/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", "Qwen3-4B text encoder", 2.5), _FLUX2_VAE),
    ),
    Recipe(
        ("klein-9b", "klein_9b", "klein-base-9b", "klein_base_9b"),
        (Companion("--llm", "unsloth/Qwen3-8B-GGUF", "Qwen3-8B-Q4_K_M.gguf", "Qwen3-8B text encoder", 5.0), _FLUX2_VAE),
    ),
    Recipe(("flux1-", "flux1_", "flux.1-", "flux-1-"), (_CLIP_L, _T5XXL, _FLUX1_VAE)),
    Recipe(
        ("sd3.5", "sd3_5", "sd3-5", "sd3_medium", "sd3-medium"),
        (
            Companion(
                "--clip_l",
                "Comfy-Org/stable-diffusion-3.5-fp8",
                "text_encoders/clip_l.safetensors",
                "CLIP-L text encoder",
                0.25,
            ),
            Companion(
                "--clip_g",
                "Comfy-Org/stable-diffusion-3.5-fp8",
                "text_encoders/clip_g.safetensors",
                "CLIP-G text encoder",
                1.4,
            ),
            Companion(
                "--t5xxl",
                "Comfy-Org/stable-diffusion-3.5-fp8",
                "text_encoders/t5xxl_fp8_e4m3fn.safetensors",
                "T5-XXL text encoder",
                4.9,
            ),
        ),
    ),
    Recipe(
        ("qwen_image", "qwen-image"),
        (
            Companion(
                "--llm",
                "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF",
                "Qwen2.5-VL-7B-Instruct.Q4_K_M.gguf",
                "Qwen2.5-VL-7B text encoder",
                4.7,
            ),
            Companion(
                "--vae",
                "Comfy-Org/Qwen-Image_ComfyUI",
                "split_files/vae/qwen_image_vae.safetensors",
                "Qwen-Image VAE",
                0.25,
            ),
        ),
        exclude=("edit",),  # Qwen-Image-Edit also needs a vision encoder
    ),
)


class ImageCompanions:
    @staticmethod
    def dir_for(model_path: Path) -> Path:
        return model_path.parent / FOLDER

    @staticmethod
    def for_model(model_path: Path) -> tuple[Companion, ...]:
        name = model_path.name.lower()
        return next((r.files for r in RECIPES if r.matches(name)), ())

    @classmethod
    def missing(cls, model_path: Path) -> list[Companion]:
        return [c for c in cls.for_model(model_path) if not (cls.dir_for(model_path) / c.local_name).is_file()]

    @classmethod
    def args(cls, model_path: Path) -> dict[str, str]:
        """{"--llm": path, "--vae": path} for companions already on disk."""
        paths = {c.flag: cls.dir_for(model_path) / c.local_name for c in cls.for_model(model_path)}
        return {flag: str(path) for flag, path in paths.items() if path.is_file()}

    @classmethod
    async def download(cls, model_path: Path, flags: list[str], proxy_url: str | None) -> AsyncIterator[dict]:
        """Downloads the missing companions among `flags` (the user's choice) as progress events; the last is
        {"error":...} on failure."""
        for c in cls.missing(model_path):
            if c.flag not in flags:
                continue
            async for event in stream_file(c.url, cls.dir_for(model_path) / c.local_name, proxy_url, c.label):
                yield event
                if "error" in event:
                    return

    @classmethod
    def remove(cls, model_path: Path) -> None:
        shutil.rmtree(cls.dir_for(model_path), ignore_errors=True)
