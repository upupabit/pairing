"""Interactive API docs (/docs, /redoc) and the schema (/openapi.json), for admins only. FastAPI's public
defaults are off (app/main.py): the route list maps every admin endpoint, so it stays behind the login.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import APP_NAME
from app.database import get_db
from app.models import User
from app.services.auth_service import PageAuth, require_admin

router = APIRouter(include_in_schema=False)

OPENAPI_URL = "/openapi.json"


@router.get(OPENAPI_URL, response_class=JSONResponse)
async def openapi_schema(request: Request, _admin: User = Depends(require_admin)) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@router.get("/docs", response_class=HTMLResponse)
async def swagger_ui(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    auth = await PageAuth(request, db).resolve()
    if isinstance(user := auth.require_admin(), RedirectResponse):
        return user
    return get_swagger_ui_html(openapi_url=OPENAPI_URL, title=f"{APP_NAME} API")


@router.get("/redoc", response_class=HTMLResponse)
async def redoc(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    auth = await PageAuth(request, db).resolve()
    if isinstance(user := auth.require_admin(), RedirectResponse):
        return user
    return get_redoc_html(openapi_url=OPENAPI_URL, title=f"{APP_NAME} API")
