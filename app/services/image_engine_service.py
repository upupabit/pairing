"""Persistence for image-engine settings: which engine serves the Images page, and the stable-diffusion.cpp
config. Split from settings_service for the file-size rule.
"""

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.schemas import DEFAULT_IMAGE_ENGINE, ImageEngineName, SdCppConfig

ACTIVE_IMAGE_ENGINE_KEY = "active_image_engine"
SDCPP_CONFIG_KEY = "sdcpp_config"
# Selectable engines. ComfyUI was removed; a selection an older version saved falls back to the default.
ENABLED_IMAGE_ENGINES: tuple[str, ...] = ("sdcpp",)


async def _put(db: AsyncSession, key: str, value: dict) -> None:
    row = await db.get(AppSetting, (SYSTEM_OWNER_ID, key))
    if row is None:
        db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=key, value=value))
    else:
        row.value = value
    await db.commit()


async def get_active_image_engine(db: AsyncSession) -> ImageEngineName:
    row = await db.get(AppSetting, (SYSTEM_OWNER_ID, ACTIVE_IMAGE_ENGINE_KEY))
    engine = row.value["engine"] if row else DEFAULT_IMAGE_ENGINE
    return engine if engine in ENABLED_IMAGE_ENGINES else DEFAULT_IMAGE_ENGINE


async def set_active_image_engine(db: AsyncSession, engine: ImageEngineName) -> None:
    """ValueError (-> 400) for a switched-off engine."""
    if engine not in ENABLED_IMAGE_ENGINES:
        raise ValueError(f"The {engine} image engine is no longer available.")
    await _put(db, ACTIVE_IMAGE_ENGINE_KEY, {"engine": engine})


def _relocated_model(model_path: str | None, models_path: str | None) -> str | None:
    """A saved model outside the models folder (set before the folder moved) points at the same
    <org>/<repo>/<file> inside it, when that copy exists; otherwise unchanged.
    """
    if not model_path or not models_path:
        return model_path
    saved, root = Path(model_path), Path(models_path)
    if saved.is_relative_to(root) or len(saved.parts) < 4:
        return model_path
    moved = root.joinpath(*saved.parts[-3:])
    return str(moved) if moved.is_file() else model_path


async def get_sdcpp_config(db: AsyncSession) -> SdCppConfig:
    row = await db.get(AppSetting, (SYSTEM_OWNER_ID, SDCPP_CONFIG_KEY))
    config = SdCppConfig(**row.value) if row else SdCppConfig()
    config.model_path = _relocated_model(config.model_path, config.models_path)
    return config


async def set_sdcpp_config(db: AsyncSession, config: SdCppConfig) -> None:
    await _put(db, SDCPP_CONFIG_KEY, config.model_dump())


def check_images_dir(path: str | None) -> None:
    """ValueError (-> 400) unless `path` is blank or an existing, writable, absolute folder (never created)."""
    if not path:
        return
    folder = Path(path).expanduser()
    if not folder.is_absolute():
        raise ValueError(f"The images folder must be an absolute path: {path}")
    if not folder.is_dir():
        raise ValueError(f"The images folder does not exist: {path}")
    if not os.access(folder, os.W_OK | os.X_OK):
        raise ValueError(f"The images folder is not writable: {path}")


async def images_root(db: AsyncSession, default: Path) -> Path:
    """Where generated images are saved: the configured folder, else `default` (app.config.IMAGES_DIR)."""
    path = (await get_sdcpp_config(db)).images_path
    return Path(path).expanduser() if path else default


async def find_image(db: AsyncSession, default: Path, relative: str) -> Path | None:
    """A saved image's file: under the configured root, else `default` (images made before a folder change stay
    put; it never moves them). None if neither has it.
    """
    for root in (await images_root(db, default), default):
        if (root / relative).is_file():
            return root / relative
    return None
