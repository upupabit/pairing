"""Inference engines > Matricxon: the experimental "wider CPU instructions" and "fused GPU kernels"
options reach a local Matricxon's environment and .env, and need a restart."""

from app.schemas import MatricxonServerConfig
from app.services import matricxon_process
from app.services.matricxon_live_settings import MatricxonSettingsPlan
from tests.test_matricxon_process import _make_checkout


def test_both_are_off_by_default_and_passed_when_on():
    env = matricxon_process._build_env(MatricxonServerConfig())
    assert env["MATRICXON_WIDE_SIMD"] == "false" and env["MATRICXON_GPU_FUSED_KERNELS"] == "false"
    env = matricxon_process._build_env(MatricxonServerConfig(wide_simd=True, gpu_fused_kernels=True))
    assert env["MATRICXON_WIDE_SIMD"] == "true" and env["MATRICXON_GPU_FUSED_KERNELS"] == "true"


def test_they_are_written_to_the_checkouts_env_file(tmp_path):
    checkout = _make_checkout(tmp_path)
    matricxon_process.write_env_file(
        MatricxonServerConfig(project_dir=str(checkout), wide_simd=True, gpu_fused_kernels=False)
    )
    env_text = (checkout / ".env").read_text()
    assert "MATRICXON_WIDE_SIMD=true" in env_text and "MATRICXON_GPU_FUSED_KERNELS=false" in env_text


def test_changing_them_asks_for_a_restart():
    old = MatricxonServerConfig()
    plan = MatricxonSettingsPlan(old, old.model_copy(update={"wide_simd": True, "gpu_fused_kernels": True}))
    assert plan.restart_required
    assert plan.restart_labels == ["Wider CPU instructions", "Fused GPU kernels"]
    assert plan.live_payload() == {}
