"""Writes tiny GGUF files (header metadata only, no tensors) for tests of the local GGUF readers and the store."""

import json
import struct
from pathlib import Path

_STRING, _UINT32 = 8, 4


def _string(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def write_gguf(path: Path, metadata: dict[str, str | int]) -> Path:
    """String values become GGUF strings, ints uint32s."""
    body = b""
    for key, value in metadata.items():
        if isinstance(value, str):
            body += _string(key) + struct.pack("<I", _STRING) + _string(value)
        else:
            body += _string(key) + struct.pack("<I", _UINT32) + struct.pack("<I", value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(metadata)) + body)
    return path


def install_model(root: Path, tag: str, metadata: dict[str, str | int], architecture: str | None = None) -> Path:
    """A model as gguf_direct_puller leaves it: `<root>/hf.co/<repo>/<file>.gguf` plus its Matricxon sidecar."""
    repo_id, _, stem = tag.removeprefix("hf.co/").partition(":")
    path = write_gguf(root / "hf.co" / repo_id / f"{stem}.gguf", metadata)
    sidecar = {
        "tag": tag,
        "path": str(path),
        "architecture": architecture or metadata.get("general.architecture", "unknown"),
        "capabilities": ["completion"],
        "size_bytes": path.stat().st_size,
        "family": architecture or metadata.get("general.architecture", "unknown"),
        "parameter_size": "1.0B",
        "context_length": 4096,
    }
    (path.parent / f"{stem}.gguf.json").write_text(json.dumps(sidecar))
    return path
