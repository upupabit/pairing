"""Tests for services/llamacpp_process.py (argv, binary discovery, status) and llamacpp_installer.py (asset names,
extraction). No real llama-server is started.
"""

import io
import tarfile

import httpx
import pytest

from app.schemas import LlamaCppServerConfig
from app.services import llamacpp_installer, llamacpp_preset, llamacpp_process
from app.services.llamacpp_installer import LlamaCppInstaller


def test_argv_runs_the_router_on_its_fixed_port_with_the_preset():
    argv = llamacpp_process.build_argv("/bin/llama-server", LlamaCppServerConfig())

    assert argv[:7] == [
        "/bin/llama-server",
        "--host",
        "127.0.0.1",
        "--port",
        "8091",
        "--models-preset",
        str(llamacpp_preset.PRESET_PATH),
    ]
    assert argv[7:] == ["--parallel", "1", "--sleep-idle-seconds", "300"]


def test_argv_carries_every_local_option():
    config = LlamaCppServerConfig(
        num_parallel=2, max_loaded_models=1, idle_unload_seconds=0, gpu_layers=99, extra_args="--threads 8"
    )

    argv = llamacpp_process.build_argv("llama-server", config)

    assert argv[7:] == ["--parallel", "2", "--models-max", "1", "--n-gpu-layers", "99", "--threads", "8"]


def test_an_executable_override_is_used_before_any_search(tmp_path):
    binary = tmp_path / "llama-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    assert llamacpp_process.find_binary(str(binary)) == str(binary)


@pytest.mark.asyncio
async def test_status_without_a_tracked_process_is_not_running():
    status = await llamacpp_process.get_status()

    assert status.running is False and status.pid is None


@pytest.mark.parametrize(
    ("machine", "variant", "name"),
    [
        ("x86_64", None, "llama-b1-bin-ubuntu-x64.tar.gz"),
        ("aarch64", None, "llama-b1-bin-ubuntu-arm64.tar.gz"),
        ("x86_64", "vulkan", "llama-b1-bin-ubuntu-vulkan-x64.tar.gz"),
    ],
)
def test_asset_url_matches_the_release_naming(monkeypatch, machine, variant, name):
    monkeypatch.setattr(llamacpp_installer.platform, "machine", lambda: machine)

    url = LlamaCppInstaller("ggml-org/llama.cpp", "b1", variant).asset_url()

    assert url == f"https://github.com/ggml-org/llama.cpp/releases/download/b1/{name}"


def _release_archive() -> bytes:
    """The release layout: one llama-<ver>/ folder with the binary and its libraries."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in (("llama-b1/llama-server", b"#!/bin/sh\n"), ("llama-b1/libllama.so", b"lib")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_install_extracts_the_binary_flat_into_the_managed_folder(monkeypatch, tmp_path):
    archive = _release_archive()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: real_client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=archive))),
    )
    monkeypatch.setattr(LlamaCppInstaller, "install_dir", staticmethod(lambda: tmp_path / "llama.cpp"))
    monkeypatch.setattr(llamacpp_installer, "MANAGED_BINARY", tmp_path / "llama.cpp" / "llama-server")
    monkeypatch.setattr(llamacpp_installer, "local_install_supported", lambda: True)

    events = [e async for e in LlamaCppInstaller(version="b1").install_stream()]

    assert events[-1]["done"] is True
    assert (tmp_path / "llama.cpp" / "llama-server").exists()
    assert (tmp_path / "llama.cpp" / "libllama.so").exists()
    assert not (tmp_path / "llama.cpp" / "llama.cpp.tar.gz").exists()


@pytest.mark.asyncio
async def test_install_refuses_off_linux(monkeypatch):
    monkeypatch.setattr(llamacpp_installer, "local_install_supported", lambda: False)

    [event] = [e async for e in LlamaCppInstaller().install_stream()]

    assert "Linux-only" in event["error"]
