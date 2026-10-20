"""Reads the few GGUF header keys llama.cpp's capability inference needs from a local, installed file
(llamacpp_capabilities): architecture, pooling type and chat template. Reuses gguf_probe's binary helpers;
that module reads remote files by range request, this one reads the disk.
"""

import logging
import struct
from dataclasses import dataclass
from pathlib import Path

from app.services.gguf_probe import _MAGIC, _SCALAR_TYPES, _STRING_TYPE, _BufferExhausted, _read_string, _skip_value

logger = logging.getLogger("llama_chat")

# A large vocab plus its chat template fits the first; the second is for unusual files.
_READ_SIZES = (32 * 1024 * 1024, 256 * 1024 * 1024)


@dataclass(frozen=True)
class GgufLocalMetadata:
    architecture: str | None = None
    # `<arch>.pooling_type`: set on embedding (1-3) and rerank (4) models, absent on chat models.
    pooling_type: int | None = None
    chat_template: str | None = None

    @classmethod
    def read(cls, path: Path) -> "GgufLocalMetadata":
        """Empty metadata on any failure: inference then falls back to plain "completion"."""
        for size in _READ_SIZES:
            try:
                with path.open("rb") as handle:
                    data = handle.read(size)
                return cls._parse(data, complete=len(data) < size)
            except _BufferExhausted:
                continue
            except Exception:  # noqa: BLE001 - an unexpected file must not break the model list
                logger.warning("Could not read GGUF metadata from %s", path, exc_info=True)
                break
        return cls()

    @classmethod
    def _parse(cls, data: bytes, complete: bool) -> "GgufLocalMetadata":
        if data[:4] != _MAGIC or len(data) < 24:
            return cls()
        (kv_count,) = struct.unpack_from("<Q", data, 16)
        offset = 24
        found: dict = {}
        try:
            for _ in range(kv_count):
                key, offset = _read_string(data, offset)
                if offset + 4 > len(data):
                    raise _BufferExhausted
                (value_type,) = struct.unpack_from("<I", data, offset)
                offset += 4
                if value_type == _STRING_TYPE and key in ("general.architecture", "tokenizer.chat_template"):
                    found[key], offset = _read_string(data, offset)
                elif key.endswith(".pooling_type") and value_type in _SCALAR_TYPES:
                    fmt, size = _SCALAR_TYPES[value_type]
                    if offset + size > len(data):
                        raise _BufferExhausted
                    (found["pooling_type"],) = struct.unpack_from(fmt, data, offset)
                    offset += size
                else:
                    offset = _skip_value(data, offset, value_type)
        except _BufferExhausted:
            if not complete:
                raise
        return cls(
            architecture=found.get("general.architecture"),
            pooling_type=found.get("pooling_type"),
            chat_template=found.get("tokenizer.chat_template"),
        )
