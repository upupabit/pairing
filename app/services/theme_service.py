"""The user's app-wide UI theme (backgrounds, text, accents, fonts; static/css/themes.css). Split from
settings_service.py (at the line cap); same get_x/set_x per-user shape (e.g. get_default_model/set_default_model).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, User
from app.theme_config import DEFAULT_UI_THEME, NEW_ACCOUNT_UI_THEME, RENAMED_UI_THEMES, UI_THEMES

THEME_KEY = "ui_theme"


async def get_ui_theme(db: AsyncSession, user: User) -> str:
    """`user`'s UI theme (app.theme_config.UI_THEMES), falling back to DEFAULT_UI_THEME if unset or no longer a valid
    theme id. A removed theme maps to its replacement (RENAMED_UI_THEMES)."""
    row = await db.get(AppSetting, (user.id, THEME_KEY))
    theme = RENAMED_UI_THEMES.get(row.value["theme"], row.value["theme"]) if row else None
    return theme if theme in {t["id"] for t in UI_THEMES} else DEFAULT_UI_THEME


def start_ui_theme(db: AsyncSession, user: User) -> None:
    """Saves NEW_ACCOUNT_UI_THEME for a just-created account (needs `user.id`); the caller commits."""
    db.add(AppSetting(owner_id=user.id, key=THEME_KEY, value={"theme": NEW_ACCOUNT_UI_THEME}))


async def set_ui_theme(db: AsyncSession, user: User, theme: str) -> None:
    row = await db.get(AppSetting, (user.id, THEME_KEY))
    value = {"theme": theme}
    if row is None:
        db.add(AppSetting(owner_id=user.id, key=THEME_KEY, value=value))
    else:
        row.value = value
    await db.commit()
