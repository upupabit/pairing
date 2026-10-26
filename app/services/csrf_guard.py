"""CSRF protection by origin check (OWASP's primary defence): a state-changing request (POST/PUT/PATCH/DELETE)
that carries the login cookie must come from a page of this server. SameSite=Lax alone doesn't cover other apps on
the same host (another port is the same "site"), so they could post with the user's cookie.

The browser's Origin (else Referer) host must match the request's Host, or X-Forwarded-Host when the direct client
is loopback (instance_proxy.py's balancer or a reverse proxy on this machine), or an entry of CSRF_TRUSTED_ORIGINS.
No Origin and no Referer: not a browser (scripts, server-to-server), so allowed. A raw ASGI middleware, like
instance_proxy.py, so streamed replies pass through untouched.
"""

import json
from urllib.parse import urlsplit

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_LOOPBACK = ("127.0.0.1", "::1")
_DEFAULT_PORTS = ("80", "443")


class CsrfOriginMiddleware:
    def __init__(self, app, cookie_name: str, trusted_origins: list[str] | None = None) -> None:
        self.app = app
        self._cookie_marker = f"{cookie_name}=".encode()
        self._trusted = {self._host_of(o if "//" in o else "//" + o) for o in trusted_origins or [] if o.strip()}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS or self._allowed(scope):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "Request blocked: it did not come from a page of this server (CSRF check)."})
        await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body.encode()})

    def _allowed(self, scope) -> bool:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if self._cookie_marker not in headers.get("cookie", "").encode("latin-1"):
            return True
        source = headers.get("origin") or headers.get("referer")
        if not source:
            return True
        if source == "null":
            return False
        allowed = {self._host_of("//" + headers.get("host", ""))} | self._trusted
        client = scope.get("client")
        if client and client[0] in _LOOPBACK and headers.get("x-forwarded-host"):
            allowed.add(self._host_of("//" + headers["x-forwarded-host"].split(",")[0].strip()))
        origin_host = self._host_of(source)
        return bool(origin_host) and origin_host in allowed

    @staticmethod
    def _host_of(url: str) -> str:
        """The URL's host and port in lower case; ports 80/443 dropped (a Host header has no scheme, and a TLS
        proxy changes only the scheme)."""
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = str(parts.port) if parts.port else ""
        return f"{host}:{port}" if port and port not in _DEFAULT_PORTS else host
