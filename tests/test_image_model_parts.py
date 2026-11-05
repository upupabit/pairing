"""Tests for image_model_parts: missing text encoder/VAE from a GGUF header, and the Add warning."""

import struct

from app.services.image_model_parts import TEXT_ENCODER, VAE, ImageModelParts


def _string(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def _gguf(tensors: list[str]) -> bytes:
    """A header with one string metadata key and 1-D tensors."""
    data = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), 1)
    data += _string("general.architecture") + struct.pack("<I", 8) + _string("flux")
    for name in tensors:
        data += _string(name) + struct.pack("<I", 1) + struct.pack("<Q", 4) + struct.pack("<IQ", 0, 0)
    return data


def test_all_in_one_file_misses_nothing():
    names = ["model.diffusion_model.x", "first_stage_model.decoder.y", "cond_stage_model.transformer.z"]
    assert ImageModelParts.missing(_gguf(names)) == []


def test_split_file_misses_both():
    assert ImageModelParts.missing(_gguf(["double_blocks.0.w", "img_in.weight"])) == [TEXT_ENCODER, VAE]


def test_file_with_vae_but_no_text_encoder():
    assert ImageModelParts.missing(_gguf(["model.diffusion_model.x", "first_stage_model.y"])) == [TEXT_ENCODER]


def test_from_file_reads_a_local_header_and_rejects_non_gguf(tmp_path):
    good, bad = tmp_path / "a.gguf", tmp_path / "b.gguf"
    good.write_bytes(_gguf(["img_in.weight"]))
    bad.write_bytes(b"not a gguf file")
    assert ImageModelParts.from_file(good) == [TEXT_ENCODER, VAE]
    assert ImageModelParts.from_file(bad) is None


def test_no_warning_when_a_recipe_covers_the_missing_parts():
    assert ImageModelParts.warning("flux-2-klein-4b-Q4_K_M.gguf", [TEXT_ENCODER, VAE]) is None
    assert ImageModelParts.warning("anything.gguf", []) is None
    assert ImageModelParts.warning("anything.gguf", None) is None


def test_warning_names_only_the_uncovered_parts():
    # SD 3.5's recipe has text encoders but no VAE.
    warning = ImageModelParts.warning("sd3.5_medium-f16.gguf", [TEXT_ENCODER, VAE])
    assert "needs a VAE," in warning
    assert "text encoder" not in warning.split(",")[0]
    assert "text encoder and a VAE" in ImageModelParts.warning("hidream-q4.gguf", [TEXT_ENCODER, VAE])
