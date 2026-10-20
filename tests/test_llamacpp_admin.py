"""Tests for services/llamacpp_admin.py: pulls into the shared store (with the repo's projector), deletes, the
remote-mode refusal and preset syncing. Hugging Face and llama-server are mocked.
"""

import pytest

from app.schemas import LlamaCppServerConfig
from app.services import llamacpp_admin, llamacpp_pool, llamacpp_preset, settings_service
from app.services.gguf_direct_puller import GgufDirectPuller
from app.services.llamacpp_admin import LlamaCppDirectPuller
from app.services.llamacpp_errors import LlamaCppError
from tests.gguf_fixture import install_model

_FILES = [
    {"filename": "vlm-Q4_K_M.gguf", "size_bytes": 4, "sha256": None},
    {"filename": "mmproj-vlm-BF16.gguf", "size_bytes": 4, "sha256": None},
    {"filename": "mmproj-vlm-F16.gguf", "size_bytes": 4, "sha256": None},
]


@pytest.fixture
def remote_pool():
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig(mode="remote", remote_hosts=["http://gpu:8080"]))
    yield
    llamacpp_pool.refresh_from_config(LlamaCppServerConfig())


def test_the_projector_prefers_f16_and_is_skipped_for_a_projector():
    assert LlamaCppDirectPuller._projector_of(_FILES[0], _FILES)["filename"] == "mmproj-vlm-F16.gguf"
    assert LlamaCppDirectPuller._projector_of(_FILES[1], _FILES) is None
    assert LlamaCppDirectPuller._projector_of(_FILES[0], _FILES[:1]) is None


@pytest.mark.asyncio
async def test_sidecar_capabilities_follow_matricxons_rule(tmp_path):
    puller = LlamaCppDirectPuller(tmp_path)

    assert await puller._infer_capabilities("org/r", "m.gguf", "llama") == ["completion"]
    assert await puller._infer_capabilities("org/r", "m.gguf", "nomic-bert") == ["embedding"]
    assert await puller._infer_capabilities("org/r-thinking", "m.gguf", "qwen3") == ["completion", "thinking"]
    assert await puller._infer_capabilities("org/r", "mmproj.gguf", "clip") == []


@pytest.mark.asyncio
async def test_a_pull_also_fetches_the_projector_into_the_same_folder(monkeypatch, tmp_path):
    pulled: list[tuple[str, str]] = []

    async def fake_resolve(_repo_id, _suffix):
        return _FILES[0], 4096, _FILES

    async def fake_pull_file(self, tag, _repo_id, matched, _ctx):
        pulled.append((tag, matched["filename"]))
        yield {"status": f"pulling {matched['filename']}"}

    monkeypatch.setattr(GgufDirectPuller, "_resolve", staticmethod(fake_resolve))
    monkeypatch.setattr(GgufDirectPuller, "_pull_file", fake_pull_file)

    events = [e async for e in LlamaCppDirectPuller(tmp_path).pull_stream("hf.co/org/vlm-GGUF:vlm-Q4_K_M")]

    assert pulled == [
        ("hf.co/org/vlm-GGUF:vlm-Q4_K_M", "vlm-Q4_K_M.gguf"),
        ("hf.co/org/vlm-GGUF:mmproj-vlm-F16", "mmproj-vlm-F16.gguf"),
    ]
    assert events[-1] == {"status": "success"}


@pytest.mark.asyncio
async def test_remote_mode_refuses_pull_and_delete(remote_pool):
    with pytest.raises(LlamaCppError, match="remote llama-server"):
        [e async for e in llamacpp_admin.pull_model_stream("hf.co/org/r:m")]
    with pytest.raises(LlamaCppError, match="remote llama-server"):
        await llamacpp_admin.delete_model("hf.co/org/r:m")


@pytest.mark.asyncio
async def test_delete_removes_the_model_and_its_preset_section(db, tmp_path):
    await settings_service.set_llamacpp_server_config(db, LlamaCppServerConfig(models_path=str(tmp_path)))
    install_model(tmp_path, "hf.co/org/r-GGUF:m-Q4_K_M", {"general.architecture": "llama"})
    await llamacpp_admin.sync_preset(reload=False)
    assert "[hf.co/org/r-GGUF@m-Q4_K_M]" in llamacpp_preset.PRESET_PATH.read_text()

    await llamacpp_admin.delete_model("hf.co/org/r-GGUF:m-Q4_K_M")

    assert not (tmp_path / "hf.co").exists()
    assert "[hf.co/org/r-GGUF@m-Q4_K_M]" not in llamacpp_preset.PRESET_PATH.read_text()
    with pytest.raises(LlamaCppError, match="not installed"):
        await llamacpp_admin.delete_model("hf.co/org/r-GGUF:m-Q4_K_M")


@pytest.mark.asyncio
async def test_the_preset_uses_the_system_context_window(db, tmp_path):
    from app.services import context_window_setting

    await settings_service.set_llamacpp_server_config(db, LlamaCppServerConfig(models_path=str(tmp_path)))
    await context_window_setting.set_num_ctx(db, 8192)

    assert "ctx-size = 8192" in llamacpp_preset.PRESET_PATH.read_text()
