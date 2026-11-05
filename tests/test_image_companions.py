"""Tests for image_companions: which split models get which companion files."""

from pathlib import Path

import pytest

from app.services.image_companions import ImageCompanions


def _flags(name: str) -> list[tuple[str, str]]:
    return [(c.flag, c.repo) for c in ImageCompanions.for_model(Path("/m/org/repo") / name)]


@pytest.mark.parametrize("name", ["flux-2-klein-4b-Q4_K_M.gguf", "flux-2-klein-base-4b-Q8_0.gguf"])
def test_flux2_klein_4b_gets_qwen3_4b_and_the_flux2_vae(name):
    assert _flags(name) == [("--llm", "unsloth/Qwen3-4B-GGUF"), ("--vae", "Comfy-Org/flux2-dev")]


def test_flux2_klein_9b_gets_qwen3_8b():
    assert _flags("flux-2-klein-9b-Q4_K_M.gguf") == [
        ("--llm", "unsloth/Qwen3-8B-GGUF"),
        ("--vae", "Comfy-Org/flux2-dev"),
    ]


def test_flux1_gets_clip_l_t5xxl_and_vae():
    assert [f for f, _ in _flags("flux1-schnell-q4_k.gguf")] == ["--clip_l", "--t5xxl", "--vae"]


def test_sd35_gets_its_three_text_encoders():
    assert [f for f, _ in _flags("sd3.5_large_turbo-q4_0.gguf")] == ["--clip_l", "--clip_g", "--t5xxl"]


def test_qwen_image_edit_is_left_out():
    assert [f for f, _ in _flags("Qwen_Image-Q2_K.gguf".lower())] == ["--llm", "--vae"]
    assert _flags("qwen-image-edit-q4_k.gguf") == []


def test_unknown_model_gets_nothing():
    assert _flags("sd_turbo-f16-q8_0.gguf") == []
