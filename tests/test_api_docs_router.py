"""Tests for routers/api_docs.py: /docs, /redoc and /openapi.json for admins only (FastAPI's public ones are off)."""

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from starlette.requests import Request

from app.main import app
from app.routers import api_docs
from app.services.auth_service import require_admin


def _request(user_id: str | None) -> Request:
    session = {"user_id": user_id} if user_id else {}
    return Request({"type": "http", "method": "GET", "path": "/docs", "headers": [], "session": session, "app": app})


def test_fastapis_public_docs_are_off() -> None:
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None


@pytest.mark.asyncio
async def test_admin_gets_the_swagger_and_redoc_pages(db, admin_user) -> None:
    for handler in (api_docs.swagger_ui, api_docs.redoc):
        response = await handler(_request(admin_user.id), db=db)
        assert response.status_code == 200
        assert api_docs.OPENAPI_URL.encode() in response.body


@pytest.mark.asyncio
async def test_non_admin_and_logged_out_are_redirected(db, user) -> None:
    for handler in (api_docs.swagger_ui, api_docs.redoc):
        to_chat = await handler(_request(user.id), db=db)
        to_login = await handler(_request(None), db=db)
        assert isinstance(to_chat, RedirectResponse) and to_chat.headers["location"] == "/"
        assert isinstance(to_login, RedirectResponse) and to_login.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_schema_is_served_to_admins_and_refused_to_users(admin_user, user) -> None:
    response = await api_docs.openapi_schema(_request(admin_user.id), _admin=admin_user)
    assert b'"paths"' in response.body
    with pytest.raises(HTTPException) as refused:
        require_admin(user)
    assert refused.value.status_code == 403
