"""Which parts a diffusion GGUF lacks, read from its tensor names: an all-in-one file (SD 1.x/2.x/XL) carries its
text encoder and VAE, a split one (FLUX, Z-Image, Qwen-Image) only the diffusion weights. Lets Add warn before
a multi-GB download when no companion recipe (image_companions.RECIPES) covers what is missing.
"""

import asyncio
import logging
import struct
from pathlib import Path

import httpx

from app.services.gguf_probe import _BufferExhausted, _read_string, _skip_value
from app.services.image_companions import ImageCompanions

logger = logging.getLogger("llama_chat")

TEXT_ENCODER = "text encoder"
VAE = "VAE"
_TEXT_PREFIXES = ("cond_stage_model.", "conditioner.", "text_encoders.")
_VAE_PREFIXES = ("first_stage_model.", "vae.")
_TEXT_FLAGS = {"--llm", "--clip_l", "--clip_g", "--t5xxl"}
_RANGES = (2 * 1024 * 1024, 16 * 1024 * 1024)
_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


class ImageModelParts:
    @staticmethod
    def _tensor_names(data: bytes) -> list[str]:
        """Raises _BufferExhausted if the header runs past `data`; ValueError if not GGUF."""
        if data[:4] != b"GGUF":
            raise ValueError("Not a GGUF file.")
        if len(data) < 24:
            raise _BufferExhausted
        tensor_count, kv_count = struct.unpack_from("<QQ", data, 8)
        offset = 24
        for _ in range(kv_count):
            _, offset = _read_string(data, offset)
            if offset + 4 > len(data):
                raise _BufferExhausted
            (value_type,) = struct.unpack_from("<I", data, offset)
            offset = _skip_value(data, offset + 4, value_type)
        names = []
        for _ in range(tensor_count):
            name, offset = _read_string(data, offset)
            if offset + 4 > len(data):
                raise _BufferExhausted
            (dims,) = struct.unpack_from("<I", data, offset)
            offset += 4 + 8 * dims + 4 + 8  # dims, type, data offset
            if offset > len(data):
                raise _BufferExhausted
            names.append(name)
        return names

    @classmethod
    def missing(cls, data: bytes) -> list[str]:
        """The parts this header's tensors lack ([] for an all-in-one file)."""
        names = cls._tensor_names(data)
        parts = []
        if not any(n.startswith(_TEXT_PREFIXES) for n in names):
            parts.append(TEXT_ENCODER)
        if not any(n.startswith(_VAE_PREFIXES) for n in names):
            parts.append(VAE)
        return parts

    @classmethod
    def from_file(cls, path: Path) -> list[str] | None:
        """None when it can't be read or parsed (not GGUF, e.g. .safetensors)."""
        for size in _RANGES:
            try:
                with path.open("rb") as f:
                    return cls.missing(f.read(size))
            except _BufferExhausted:
                continue
            except Exception:
                return None
        return None

    @classmethod
    async def from_file_async(cls, path: Path) -> list[str] | None:
        return await asyncio.to_thread(cls.from_file, path)

    @classmethod
    async def from_hub(cls, repo_id: str, filename: str, proxy_url: str | None) -> list[str] | None:
        """Same, from a couple of range requests; None on any failure (best effort, never blocks Add)."""
        url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, proxy=proxy_url) as client:
            for size in _RANGES:
                try:
                    resp = await client.get(url, headers={"Range": f"bytes=0-{size - 1}"})
                    if resp.status_code not in (200, 206):
                        return None
                    return cls.missing(resp.content)
                except _BufferExhausted:
                    continue
                except Exception:
                    logger.warning("Could not read the parts of %s:%s", repo_id, filename, exc_info=True)
                    return None
        return None

    @staticmethod
    def warning(filename: str, missing: list[str] | None) -> str | None:
        """A warning when the companion recipe for `filename` doesn't cover every missing part; None otherwise."""
        flags = {c.flag for c in ImageCompanions.for_model(Path(filename))}
        unmet = [
            part for part in missing or [] if not (flags & _TEXT_FLAGS if part == TEXT_ENCODER else "--vae" in flags)
        ]
        if not unmet:
            return None
        them = "it" if len(unmet) == 1 else "them"
        return (
            f"Split model: it also needs a {' and a '.join(unmet)}, which pAIring can't download for it. "
            f"It won't start without {them}; add {them} yourself with --llm/--clip_l/--t5xxl/--vae in "
            "Settings > Image > extra args."
        )
