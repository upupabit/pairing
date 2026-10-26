"""FastAPI application factory: wires the database, API routers, static files and HTML pages. Imported by `run.py`."""

import logging
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import (
    APP_NAME,
    APP_VERSION,
    BASE_DIR,
    CSRF_TRUSTED_ORIGINS,
    INSTANCE_INDEX,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE,
)
from app.routers import (
    account,
    api_docs,
    auth,
    channel_history_admin,
    channels,
    chat,
    cluster_admin,
    connectors,
    context_window_admin,
    conversations,
    db_admin,
    documents,
    engine_admin,
    health,
    http_proxy_admin,
    image_engine_admin,
    image_generation,
    image_model_admin,
    instances_admin,
    llamacpp_admin,
    matricxon_admin,
    matricxon_cache_admin,
    mcp_admin,
    mcp_tools,
    model_capabilities,
    model_catalog_admin,
    notes,
    pages,
    proxy_admin,
    rerank_admin,
    sdcpp_admin,
    settings,
    stats,
    system_metrics,
    telemetry,
    theme,
    update_admin,
    users,
    workflow_live,
)
from app.services import startup_service
from app.services.csrf_guard import CsrfOriginMiddleware
from app.services.instance_proxy import InstanceProxyMiddleware
from app.templates_env import templates

logger = logging.getLogger("llama_chat")
logging.basicConfig(level=logging.INFO)

# Built-in /docs, /redoc and /openapi.json off: app/routers/api_docs.py serves them to admins only.
app = FastAPI(
    title=APP_NAME,
    description="On-prem, multi-user chat UI for models on a local ML engine",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class InstanceIndexHeaderMiddleware:
    """Stamps every response with X-Instance-Index (this process's app.config.INSTANCE_INDEX), on primary
    and siblings alike, so load balancing is observable from outside.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Outermost, so it also wraps InstanceProxyMiddleware. Adds the header only if missing: a proxied
                # response already carries the serving instance's.
                if not any(k.lower() == b"x-instance-index" for k, _ in message["headers"]):
                    message["headers"].append((b"x-instance-index", str(INSTANCE_INDEX).encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Signed session cookie for login (app/services/auth_service.py, app/routers/auth.py); register before
# any route reading request.session. https_only defaults to False (see SESSION_COOKIE_SECURE).
# Its own cookie name: browsers share cookies across ports, so another app on the same host using the default
# "session" cookie (e.g. piebytes) would overwrite this login. All instances behind the load balancer share it.
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, https_only=SESSION_COOKIE_SECURE, session_cookie=SESSION_COOKIE_NAME
)

# Starlette makes the last-registered middleware outermost. These two come after SessionMiddleware so a
# proxied request never touches this process's session (the target decodes the shared cookie, see instance_proxy.py).
app.add_middleware(InstanceProxyMiddleware)
app.add_middleware(InstanceIndexHeaderMiddleware)
# Outermost: checked before a request is proxied to a sibling (which checks again via X-Forwarded-Host).
app.add_middleware(CsrfOriginMiddleware, cookie_name=SESSION_COOKIE_NAME, trusted_origins=CSRF_TRUSTED_ORIGINS)

# Serves app/static/ at /static/ (no build step, no login: the login page needs it). Uses BASE_DIR so it
# works from any working directory (a relative path once crashed a systemd instance).
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")

# `templates` is shared with app/routers/auth.py and app/routers/pages.py; see app/templates_env.py for why it must be
# one instance.

# Appended as `?v=...` to /static/ URLs; changes each restart so browsers never mix cached old and new JS.
STATIC_VERSION = str(int(time.time()))
templates.env.globals["static_version"] = STATIC_VERSION
templates.env.globals["app_version"] = APP_VERSION
templates.env.globals["app_name"] = APP_NAME

# HTML page routes (app/routers/pages.py), registered like the JSON routers.
app.include_router(pages.router)

# JSON API routers by resource (see each docstring). All but auth require a logged-in user via
# get_current_user / require_admin.
app.include_router(account.router)
app.include_router(api_docs.router)
app.include_router(auth.router)
app.include_router(channels.router)
app.include_router(channels.member_router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(settings.router)
app.include_router(model_catalog_admin.router)
app.include_router(model_capabilities.router)
app.include_router(users.router)
app.include_router(db_admin.router)
app.include_router(documents.router)
app.include_router(notes.router)
app.include_router(health.router)
app.include_router(instances_admin.router)
app.include_router(image_generation.router)
app.include_router(image_engine_admin.router)
app.include_router(image_model_admin.router)
app.include_router(sdcpp_admin.router)
app.include_router(proxy_admin.router)
app.include_router(rerank_admin.router)
app.include_router(http_proxy_admin.router)
app.include_router(llamacpp_admin.router)
app.include_router(matricxon_admin.router)
app.include_router(matricxon_cache_admin.router)
app.include_router(engine_admin.router)
app.include_router(cluster_admin.router)
app.include_router(connectors.router)
app.include_router(channel_history_admin.router)
app.include_router(context_window_admin.router)
app.include_router(mcp_admin.router)
app.include_router(mcp_admin.enabled_router)
app.include_router(mcp_admin.limits_router)
app.include_router(mcp_tools.router)
app.include_router(stats.router)
app.include_router(workflow_live.router)
app.include_router(telemetry.router)
app.include_router(system_metrics.router)
app.include_router(theme.router)
app.include_router(update_admin.router)


@app.on_event("startup")
async def on_startup():
    """Work is in app.services.startup_service.run_startup_tasks (split out to keep this file compact)."""
    await startup_service.run_startup_tasks()


@app.on_event("shutdown")
async def on_shutdown():
    """See app.services.startup_service.run_shutdown_tasks."""
    await startup_service.run_shutdown_tasks()
