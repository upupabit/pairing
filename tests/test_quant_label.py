"""Tests for app/quant_label.py: the quantization label read from a model tag (model cards' badge)."""

import pytest

from app.quant_label import QuantLabel
from app.schemas.model_catalog import CatalogEntry


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("hf.co/unsloth/Llama-3.2-3B-Instruct-GGUF:Llama-3.2-3B-Instruct-Q3_K_M", "Q3_K_M"),
        ("hf.co/cjpais/llava-1.6-mistral-7b-gguf:llava-v1.6-mistral-7b.Q3_K_M", "Q3_K_M"),
        ("hf.co/leliuga/all-MiniLM-L6-v2-GGUF:Q8_0", "Q8_0"),
        ("hf.co/unsloth/MiniMax-M3-GGUF:UD-IQ1_M", "IQ1_M"),
        ("hf.co/unsloth/Llama-3.2-3B-Instruct-GGUF:Llama-3.2-3B-Instruct-UD-Q2_K_XL", "Q2_K_XL"),
        # Not only at the end, and the last token wins.
        ("hf.co/google/gemma-4-E2B-it-qat-q4_0-gguf:gemma-4-E2B_q4_0-it", "Q4_0"),
        ("hf.co/Green-Sky/SD-Turbo-GGUF:sd_turbo-f16-q8_0", "Q8_0"),
        ("hf.co/org/repo:model-IQ4_XS", "IQ4_XS"),
        ("custom:latest", None),
        ("@cf/meta/llama-3.1-8b-instruct", None),
        ("", None),
        (None, None),
    ],
)
def test_from_tag(tag, expected):
    assert QuantLabel.from_tag(tag) == expected


def test_catalog_entries_carry_the_label_for_the_frontend():
    entry = CatalogEntry(
        family="Llama",
        vendor="bartowski",
        tag="hf.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF:Meta-Llama-3.1-8B-Instruct-IQ2_M",
        parameter_size="8B",
        min_ram_gb=4,
        locally_runnable=True,
        installed=True,
        hardware_ok=True,
    )

    assert entry.model_dump()["quantization"] == "IQ2_M"
