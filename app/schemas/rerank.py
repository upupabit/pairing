"""Admin settings: the Knowledge base reranker."""

from pydantic import BaseModel, computed_field

from app.quant_label import QuantLabel


class RerankModelSetting(BaseModel):
    # The reranker in use; None when off or none is installed.
    model: str | None
    enabled: bool
    installed: list[str]
    # Whether the active engine can rerank at all.
    engine_supports: bool


class RerankModelUpdate(BaseModel):
    # None switches reranking off.
    model: str | None


class RerankCatalogEntry(BaseModel):
    family: str
    vendor: str
    tag: str
    parameter_size: str
    context_length: int | None
    download_gb: float | None
    min_ram_gb: float
    installed: bool
    # The reranker Knowledge base retrieval uses now.
    in_use: bool

    # The file's quantization (e.g. "Q8_0"), read from its tag; shown as a badge.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def quantization(self) -> str | None:
        return QuantLabel.from_tag(self.tag)


class RerankModelCatalogResponse(BaseModel):
    engine_supports: bool
    entries: list[RerankCatalogEntry]
