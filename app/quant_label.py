"""The quantization label of a model file (e.g. "Q4_K_M", "IQ2_M"), read from its `hf.co/<repo>:<file>` tag, for the
model cards' badge (CatalogEntry.quantization) and for naming an unknown model. A pure helper with no app imports, so
schemas and services can both use it.
"""

import re


class QuantLabel:
    # A whole quant token anywhere in the file name, not only at its end ("gemma-4-E2B_q4_0-it"); the last one wins
    # ("sd_turbo-f16-q8_0" -> Q8_0). Longer forms first, so "Q4_K_M" isn't read as "Q4_K".
    _TOKEN = re.compile(
        r"(?<![A-Za-z0-9])"
        r"(IQ\d_(?:XXS|XS|NL|S|M)|TQ\d_\d|Q\d_K_(?:XL|S|M|L)|Q\d_K|Q\d_\d|BF16|FP16|F16|FP32|F32)"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )

    @classmethod
    def from_tag(cls, tag: str | None) -> str | None:
        """None when the tag names no recognizable quantization (e.g. a cloud connector's model id)."""
        if not tag:
            return None
        matches = cls._TOKEN.findall(tag.rsplit(":", 1)[-1])
        return matches[-1].upper() if matches else None
