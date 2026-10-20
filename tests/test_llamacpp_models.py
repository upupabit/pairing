"""Tests for services/llamacpp_models.py and llamacpp_preset.py: router names, capability inference from GGUF
headers, the model list shape, the models folder and the preset INI.
"""

from pathlib import Path

from app.schemas import LlamaCppServerConfig, MatricxonServerConfig
from app.services import llamacpp_models
from app.services.gguf_model_store import GgufModelStore
from app.services.llamacpp_models import LlamaCppCatalog, LlamaCppModelName, LlamaCppModelsFolder
from app.services.llamacpp_preset import LlamaCppPreset
from tests.gguf_fixture import install_model

_CHAT = "hf.co/org/chat-GGUF:chat-Q4_K_M"


def test_router_names_keep_the_tag_without_a_colon():
    # The router rewrites "<repo>:<tag>" names to the quant alone, so ":" must not reach it.
    assert LlamaCppModelName.to_router(_CHAT) == "hf.co/org/chat-GGUF@chat-Q4_K_M"
    assert LlamaCppModelName.from_router("hf.co/org/chat-GGUF@chat-Q4_K_M") == _CHAT
    assert LlamaCppModelName.from_router("plain@name") == "plain@name"


def _capabilities(tmp_path: Path, metadata: dict, tag: str = _CHAT) -> list[str]:
    install_model(tmp_path, tag, metadata)
    [(_model, _projector, capabilities)] = LlamaCppCatalog(GgufModelStore(tmp_path)).entries()
    return capabilities


def test_a_chat_model_with_a_tool_template_can_use_tools(tmp_path):
    caps = _capabilities(tmp_path, {"general.architecture": "llama", "tokenizer.chat_template": "{% if tools %}"})
    assert caps == ["completion", "tools"]


def test_a_pooled_model_is_an_embedding_model(tmp_path):
    assert _capabilities(tmp_path, {"general.architecture": "qwen3", "qwen3.pooling_type": 1}) == ["embedding"]


def test_an_encoder_without_pooling_metadata_is_still_an_embedding_model(tmp_path):
    assert _capabilities(tmp_path, {"general.architecture": "bert"}) == ["embedding"]


def test_rank_pooling_is_a_reranker(tmp_path):
    assert _capabilities(tmp_path, {"general.architecture": "qwen3", "qwen3.pooling_type": 4}) == ["rerank"]


def test_a_projector_has_no_capabilities_and_gives_its_model_vision(tmp_path):
    install_model(tmp_path, _CHAT, {"general.architecture": "gemma3"})
    install_model(tmp_path, "hf.co/org/chat-GGUF:mmproj-F16", {"general.architecture": "clip"})

    listed = {m["name"]: m for m in LlamaCppCatalog(GgufModelStore(tmp_path)).list_models()}

    assert listed[_CHAT]["capabilities"] == ["completion", "vision"]
    assert listed["hf.co/org/chat-GGUF:mmproj-F16"]["capabilities"] == []
    assert listed["hf.co/org/chat-GGUF:mmproj-F16"]["details"]["family"] == "clip"


def test_the_models_folder_is_the_override_then_matricxons_then_the_fallback(tmp_path, monkeypatch):
    shared = LlamaCppModelsFolder.resolve(LlamaCppServerConfig(), MatricxonServerConfig(models_path=str(tmp_path)))
    own = LlamaCppModelsFolder.resolve(
        LlamaCppServerConfig(models_path="/data/llama"), MatricxonServerConfig(models_path=str(tmp_path))
    )
    fallback = LlamaCppModelsFolder.resolve(LlamaCppServerConfig(), MatricxonServerConfig())

    assert shared == tmp_path
    assert own == Path("/data/llama")
    assert fallback == llamacpp_models.FALLBACK_MODELS_DIR


def test_the_preset_has_one_section_per_runnable_model(tmp_path):
    install_model(tmp_path, _CHAT, {"general.architecture": "gemma3"})
    projector = install_model(tmp_path, "hf.co/org/chat-GGUF:mmproj-F16", {"general.architecture": "clip"})
    embedder = install_model(tmp_path, "hf.co/org/emb-GGUF:Q8_0", {"general.architecture": "bert"})
    entries = LlamaCppCatalog(GgufModelStore(tmp_path)).entries()

    text = LlamaCppPreset(entries, num_ctx=4096, slots=2).render()

    assert "[*]\nctx-size = 8192" in text
    assert f"[hf.co/org/chat-GGUF@chat-Q4_K_M]\nmodel = {tmp_path}/hf.co/org/chat-GGUF/chat-Q4_K_M.gguf" in text
    assert f"mmproj = {projector}" in text
    assert f"[hf.co/org/emb-GGUF@Q8_0]\nmodel = {embedder}\nembeddings = true" in text
    assert "mmproj-F16]" not in text


def test_writing_the_preset_reports_whether_it_changed(tmp_path):
    preset = LlamaCppPreset([], num_ctx=2048, slots=1)
    path = tmp_path / "models.ini"

    assert preset.write(path) is True
    assert preset.write(path) is False
    assert LlamaCppPreset([], num_ctx=4096, slots=1).write(path) is True
