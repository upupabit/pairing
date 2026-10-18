"""The login cookie has its own name, so other apps on the same host (any port) don't overwrite it."""

from starlette.middleware.sessions import SessionMiddleware


def test_the_login_cookie_is_not_the_default_session() -> None:
    from app.main import app

    middleware = next(m for m in app.user_middleware if m.cls is SessionMiddleware)
    assert middleware.kwargs["session_cookie"] == "pairing_session"
