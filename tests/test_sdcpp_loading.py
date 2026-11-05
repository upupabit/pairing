"""A started sd-server still reading its model: reported as loading, and jobs wait for it."""

import base64

import pytest

from app.services import image_engine_service, image_generation_service, sdcpp_client, sdcpp_process, sdcpp_service
from tests.test_image_generation_service import _request


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sdcpp_process, "_TRACKING_FILE", tmp_path / "sdcpp.json")
    monkeypatch.setattr(sdcpp_process, "_LOG_PATH", tmp_path / "sdcpp.log")
    (tmp_path / "sdcpp.log").write_text("old run\\nlistening on: http://127.0.0.1:8189\\n")
    return tmp_path / "sdcpp.log"


def _track(alive=True, monkeypatch=None):
    sdcpp_process.write_tracking({"pid": 7, "log_offset": sdcpp_process.log_offset(), "binary_path": "/sd"})
    monkeypatch.setattr(sdcpp_process, "is_alive", lambda *_a: alive)


def test_loading_until_this_launch_logs_ready(isolated_files, monkeypatch):
    _track(monkeypatch=monkeypatch)
    with isolated_files.open("a") as log:
        log.write("loading model from '/m.gguf'\\n")
    assert sdcpp_process.is_loading() is True

    with isolated_files.open("a") as log:
        log.write("[INFO] main.cpp:149 - listening on: http://127.0.0.1:8189\\n")
    assert sdcpp_process.is_loading() is False


def test_not_loading_when_dead_or_untracked(monkeypatch):
    assert sdcpp_process.is_loading() is False
    _track(alive=False, monkeypatch=monkeypatch)
    assert sdcpp_process.is_loading() is False


@pytest.mark.asyncio
async def test_status_says_loading_instead_of_not_responding(db, monkeypatch):
    from app.schemas import SdCppConfig

    await image_engine_service.set_sdcpp_config(db, SdCppConfig(binary_path="/sd"))
    _track(monkeypatch=monkeypatch)

    async def unhealthy():
        return False

    monkeypatch.setattr(sdcpp_service, "_ping_health", unhealthy)
    status = await sdcpp_service.get_status(db)
    assert status.running and status.loading and status.healthy is False


@pytest.mark.asyncio
async def test_job_waits_for_the_model_to_load_before_submitting(db, user, tmp_path, monkeypatch):
    monkeypatch.setattr(image_generation_service, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(image_generation_service, "_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(image_generation_service, "_schedule", lambda _job_id: None)
    await image_engine_service.set_active_image_engine(db, "sdcpp")
    checks = iter([True, True, False])
    monkeypatch.setattr(sdcpp_process, "is_loading", lambda: next(checks))
    submitted = []

    async def fake_submit(params):
        submitted.append(params)
        return "http://h1:8189", "job_1"

    async def fake_get(_host, _job_id):
        return {"status": "completed", "result": {"images": [{"b64_json": base64.b64encode(b"png").decode()}]}}

    monkeypatch.setattr(sdcpp_client, "submit_job", fake_submit)
    monkeypatch.setattr(sdcpp_client, "get_job", fake_get)

    job = await image_generation_service.create_job(db, user.id, _request())
    await image_generation_service._run_job(job.id)

    await db.refresh(job)
    assert job.status == "complete" and len(submitted) == 1
