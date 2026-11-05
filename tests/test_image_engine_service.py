"""Tests for image_engine_service: a saved model path follows a moved models folder."""

import pytest

from app.schemas import SdCppConfig
from app.services import image_engine_service


@pytest.mark.asyncio
async def test_saved_model_outside_the_folder_points_at_its_copy_inside(db, tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        (root / "org" / "repo").mkdir(parents=True)
        (root / "org" / "repo" / "m.gguf").write_bytes(b"x")
    saved = SdCppConfig(model_path=str(old / "org/repo/m.gguf"), models_path=str(new))
    await image_engine_service.set_sdcpp_config(db, saved)

    config = await image_engine_service.get_sdcpp_config(db)

    assert config.model_path == str(new / "org/repo/m.gguf")


@pytest.mark.asyncio
async def test_saved_model_without_a_copy_in_the_folder_is_kept(db, tmp_path):
    old = tmp_path / "old" / "org" / "repo"
    old.mkdir(parents=True)
    (old / "m.gguf").write_bytes(b"x")
    saved = SdCppConfig(model_path=str(old / "m.gguf"), models_path=str(tmp_path / "new"))
    await image_engine_service.set_sdcpp_config(db, saved)

    config = await image_engine_service.get_sdcpp_config(db)

    assert config.model_path == str(old / "m.gguf")
