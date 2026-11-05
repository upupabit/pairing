"""The split-model warning end to end: Add's response and the Diffusion models rows."""

import pytest

from app.routers import model_catalog_admin
from app.schemas import AddExtendedModelRequest
from app.services import extended_model_catalog_service as svc, image_model_service
from app.services.huggingface_client import HuggingFaceCatalogSearch
from app.services.image_model_parts import TEXT_ENCODER, VAE, ImageModelParts
from tests.test_image_model_parts import _gguf

_REPO = "org/HiDream-GGUF"
_FILE = "hidream-q4_k.gguf"


async def _async(value):
    return value


@pytest.fixture
def models_root(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    monkeypatch.setattr(image_model_service, "resolve_models_dir", lambda _db: _async(root))
    return root


@pytest.fixture
def split_repo(monkeypatch):
    repo = {
        "repo_id": _REPO,
        "is_image": True,
        "parameter_size": None,
        "files": [{"filename": _FILE, "download_gb": 9.0}],
    }
    monkeypatch.setattr(HuggingFaceCatalogSearch, "repo_files", staticmethod(lambda *_a: _async(repo)))
    monkeypatch.setattr(svc, "list_models", lambda: _async([]))
    monkeypatch.setattr(ImageModelParts, "from_hub", classmethod(lambda cls, *_a: _async([TEXT_ENCODER, VAE])))


@pytest.mark.asyncio
async def test_add_warns_about_a_split_model_without_a_recipe(db, admin_user, models_root, split_repo):
    result = await model_catalog_admin.add_extended_model(
        AddExtendedModelRequest(repo_id=_REPO, filename=_FILE), db=db, admin=admin_user
    )

    assert "text encoder and a VAE" in result.warning
    rows = await image_model_service.ImageModelStore(db, models_root).catalog_entries(is_admin=True)
    assert [r.warning is not None for r in rows if r.tag.startswith(f"hf.co/{_REPO}")] == [True]


@pytest.mark.asyncio
async def test_installed_file_is_checked_from_disk(db, models_root):
    split = models_root / "org" / "Mystery-GGUF" / "mystery-q4.gguf"
    whole = models_root / "org" / "Whole-GGUF" / "whole-q8.gguf"
    for path, names in (
        (split, ["img_in.weight"]),
        (whole, ["model.diffusion_model.x", "first_stage_model.y", "conditioner.z"]),
    ):
        path.parent.mkdir(parents=True)
        path.write_bytes(_gguf(names))

    rows = await image_model_service.ImageModelStore(db, models_root).catalog_entries()

    warnings = {r.tag.rsplit(":", 1)[-1]: r.warning for r in rows if r.installed}
    assert warnings["whole-q8"] is None
    assert "text encoder and a VAE" in warnings["mystery-q4"]


@pytest.mark.asyncio
async def test_listing_flags_a_saved_engine_model_whose_file_is_gone(db, models_root):
    from app.routers import image_model_admin
    from app.schemas import SdCppConfig
    from app.services import image_engine_service

    gone = str(models_root / "org" / "repo" / "old" / "deleted.gguf")
    await image_engine_service.set_sdcpp_config(db, SdCppConfig(model_path=gone))
    assert (await image_model_admin.list_image_models(db=db, _admin=None)).engine_model_missing == gone

    kept = models_root / "org" / "repo" / "kept.gguf"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"x")
    await image_engine_service.set_sdcpp_config(db, SdCppConfig(model_path=str(kept)))
    assert (await image_model_admin.list_image_models(db=db, _admin=None)).engine_model_missing is None
