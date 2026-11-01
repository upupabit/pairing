"""HTTP client for Matricxon calls: signs each request with the admin secret when one is set, and
sends the API key when one is set.

Matricxon checks the signature on its admin routes (reset, provision, voters, pull, delete, cache
policy...) and the key on the routes that run a model (MATRICXON_API_KEYS). Extra headers on other
routes are ignored, so every Matricxon call can use `client()`.
Mirrors ../matricxon/app/server/admin_auth.py and api_keys.py.
"""

import hashlib
import hmac
import secrets
import time
from collections.abc import Generator
from typing import Any

import httpx

_secret: str | None = None
_api_key: str | None = None


def set_secret(secret: str | None) -> None:
    """Called when the Matricxon config loads or changes (matricxon_pool.refresh_from_config)."""
    global _secret
    _secret = secret or None


def set_api_key(key: str | None) -> None:
    """Called with set_secret (matricxon_pool.refresh_from_config)."""
    global _api_key
    _api_key = key or None


def signature(secret: str, method: str, target: str, body: bytes, stamp: str, nonce: str) -> str:
    key = hashlib.sha256(b"matricxon-admin|" + secret.encode()).digest()
    text = f"{stamp}\n{nonce}\n{method.upper()}\n{target}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


class _Signer(httpx.Auth):
    requires_request_body = True

    def __init__(self, secret_of=lambda: _secret, key_of=lambda: _api_key) -> None:
        self._secret_of = secret_of
        self._key_of = key_of

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        key = self._key_of()
        # A caller may name the key itself (changing the key on a node that still has the old one).
        if key and "Authorization" not in request.headers:
            request.headers["Authorization"] = f"Bearer {key}"
        secret = self._secret_of()
        if secret:
            query = request.url.query.decode()
            target = request.url.path + (f"?{query}" if query else "")
            stamp, nonce = str(time.time()), secrets.token_hex(12)
            request.headers["X-Matricxon-Time"] = stamp
            request.headers["X-Matricxon-Nonce"] = nonce
            request.headers["X-Matricxon-Signature"] = signature(
                secret, request.method, target, request.content, stamp, nonce
            )
        yield request


def client(**kwargs: Any) -> httpx.AsyncClient:
    """An `httpx.AsyncClient` whose requests are signed while a secret is set, with the API key while one is set."""
    return httpx.AsyncClient(auth=_Signer(), **kwargs)
