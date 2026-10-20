"""Tests for services/gguf_model_store.py (the folder Matricxon and llama.cpp share) and gguf_local_metadata.py."""

import json

from app.services.gguf_local_metadata import GgufLocalMetadata
from app.services.gguf_model_store import GgufModelStore
from tests.gguf_fixture import install_model, write_gguf

_CHAT = "hf.co/org/vlm-GGUF:vlm-Q4_K_M"
_PROJECTOR = "hf.co/org/vlm-GGUF:mmproj-vlm-F16"


def test_lists_each_model_from_its_sidecar(tmp_path):
    install_model(tmp_path, _CHAT, {"general.architecture": "llama"})

    [model] = GgufModelStore(tmp_path).models()

    assert model.tag == _CHAT
    assert model.path == tmp_path / "hf.co/org/vlm-GGUF/vlm-Q4_K_M.gguf"
    assert model.architecture == "llama"


def test_a_missing_folder_lists_nothing(tmp_path):
    assert GgufModelStore(tmp_path / "absent").models() == []


def test_skips_a_broken_sidecar_or_one_whose_file_is_gone(tmp_path):
    path = install_model(tmp_path, _CHAT, {"general.architecture": "llama"})
    (tmp_path / "bad.gguf.json").write_text("{not json")
    path.unlink()

    assert GgufModelStore(tmp_path).models() == []


def test_pairs_a_projector_in_the_same_folder(tmp_path):
    install_model(tmp_path, _CHAT, {"general.architecture": "llama"})
    install_model(tmp_path, _PROJECTOR, {"general.architecture": "clip"})
    store = GgufModelStore(tmp_path)

    chat = store.get(_CHAT)
    projector = store.projector_for(chat)

    assert projector is not None and projector.tag == _PROJECTOR
    assert store.projector_for(projector) is None


def test_delete_removes_the_file_its_sidecar_and_empty_folders(tmp_path):
    install_model(tmp_path, _CHAT, {"general.architecture": "llama"})
    store = GgufModelStore(tmp_path)

    assert store.delete(_CHAT) is True

    assert not (tmp_path / "hf.co").exists()
    assert tmp_path.exists()
    assert store.delete(_CHAT) is False


def test_the_sidecar_location_wins_over_its_stored_path(tmp_path):
    path = install_model(tmp_path, _CHAT, {"general.architecture": "llama"})
    sidecar = path.parent / "vlm-Q4_K_M.gguf.json"
    sidecar.write_text(json.dumps({**json.loads(sidecar.read_text()), "path": "/moved/elsewhere.gguf"}))

    assert GgufModelStore(tmp_path).get(_CHAT).path == path


def test_local_metadata_reads_architecture_pooling_and_template(tmp_path):
    path = write_gguf(
        tmp_path / "m.gguf",
        {"general.architecture": "qwen3", "qwen3.pooling_type": 3, "tokenizer.chat_template": "{{ tools }}"},
    )

    meta = GgufLocalMetadata.read(path)

    assert (meta.architecture, meta.pooling_type, meta.chat_template) == ("qwen3", 3, "{{ tools }}")


def test_local_metadata_of_a_non_gguf_file_is_empty(tmp_path):
    path = tmp_path / "x.gguf"
    path.write_bytes(b"not a gguf at all, just text")

    assert GgufLocalMetadata.read(path) == GgufLocalMetadata()
