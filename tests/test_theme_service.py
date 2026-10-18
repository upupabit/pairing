"""Tests for services/theme_service.py's per-user UI theme getter/setter."""

from pathlib import Path

import pytest

from app.services import theme_service
from app.theme_config import DEFAULT_UI_THEME, UI_THEMES


@pytest.mark.asyncio
async def test_get_ui_theme_defaults_when_unset(db, user):
    assert await theme_service.get_ui_theme(db, user) == DEFAULT_UI_THEME


@pytest.mark.asyncio
async def test_set_ui_theme_round_trips(db, user):
    await theme_service.set_ui_theme(db, user, "plain")
    assert await theme_service.get_ui_theme(db, user) == "plain"

    await theme_service.set_ui_theme(db, user, "nord")
    assert await theme_service.get_ui_theme(db, user) == "nord"


@pytest.mark.asyncio
async def test_get_ui_theme_falls_back_to_default_for_an_invalid_saved_value(db, user):
    await theme_service.set_ui_theme(db, user, "a-theme-that-was-later-removed")
    assert await theme_service.get_ui_theme(db, user) == DEFAULT_UI_THEME


@pytest.mark.asyncio
async def test_ui_theme_is_isolated_per_user(db, user, admin_user):
    await theme_service.set_ui_theme(db, user, "bubblegum")

    assert await theme_service.get_ui_theme(db, user) == "bubblegum"
    assert await theme_service.get_ui_theme(db, admin_user) == DEFAULT_UI_THEME


@pytest.mark.asyncio
async def test_a_saved_sunshine_theme_becomes_plain(db, user):
    await theme_service.set_ui_theme(db, user, "sunshine")
    assert await theme_service.get_ui_theme(db, user) == "plain"


def test_every_theme_has_its_colors_in_the_css():
    css = "".join(p.read_text() for p in Path("app/static/css").glob("themes*.css"))
    for theme in UI_THEMES:
        assert f'[data-theme="{theme["id"]}"] {{' in css
        assert css.count(f'[data-theme="{theme["id"]}"]') == 3  # its block, solid fills, semantic ramps


@pytest.mark.asyncio
async def test_new_accounts_start_on_plain_and_older_ones_keep_the_default(db, user, monkeypatch):
    from app.schemas import UserCreate
    from app.services import auth_service, user_service

    async def installed():
        return ["llama3:latest"]

    async def default_model(_db, _installed):
        return "llama3:latest"

    monkeypatch.setattr(user_service, "installed_chat_models", installed)
    monkeypatch.setattr(user_service, "get_default_model_for_new_users", default_model)
    new = await user_service.create_user(db, UserCreate(username="dana", password="dana-pw"))
    admin = await auth_service.seed_default_users(db)

    assert await theme_service.get_ui_theme(db, new) == "plain"
    assert await theme_service.get_ui_theme(db, admin) == "plain"
    assert await theme_service.get_ui_theme(db, user) == DEFAULT_UI_THEME  # made without a saved theme
