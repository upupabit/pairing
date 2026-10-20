"""Access tokens for Google Vertex AI from a service-account key (Google's server-to-server OAuth flow): a JWT signed
with the key (RS256) is exchanged at the key's token_uri for a one-hour access token, cached and renewed 5 minutes
before it ends. Uses `cryptography` (already a dependency), not google-auth."""

import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_LIFETIME = 3600
_RENEW_BEFORE = 300
_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


class VertexAuthError(Exception):
    """The service-account key is unusable, or Google refused it."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ServiceAccountKey:
    def __init__(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            self.email: str = data["client_email"]
            self.private_key: str = data["private_key"]
        except (ValueError, KeyError, TypeError) as exc:
            raise VertexAuthError(
                "The service-account key isn't a valid JSON key file (it needs client_email and private_key)."
            ) from exc
        self.key_id: str = data.get("private_key_id", "")
        self.project_id: str = data.get("project_id", "")
        self.token_uri: str = data.get("token_uri") or _DEFAULT_TOKEN_URI

    def assertion(self, now: int) -> str:
        """The signed JWT the token endpoint takes."""
        header = {"alg": "RS256", "typ": "JWT", "kid": self.key_id}
        claims = {"iss": self.email, "scope": SCOPE, "aud": self.token_uri, "iat": now, "exp": now + _LIFETIME}
        signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
        try:
            key = serialization.load_pem_private_key(self.private_key.encode(), password=None)
        except ValueError as exc:
            raise VertexAuthError("The service-account key's private_key can't be read.") from exc
        signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr]
        return f"{signing_input}.{_b64(signature)}"


class VertexTokenSource:
    """One cached token per key (a "Test connection" with a new key never reuses the saved key's token)."""

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}

    async def token(self, raw_key: str) -> str:
        key = ServiceAccountKey(raw_key)
        cache_key = f"{key.email}:{key.key_id}"
        cached = self._tokens.get(cache_key)
        if cached and cached[1] - _RENEW_BEFORE > time.time():
            return cached[0]
        now = int(time.time())
        data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": key.assertion(now)}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(key.token_uri, data=data)
        except httpx.HTTPError as exc:
            raise VertexAuthError(f"Could not reach Google's token service: {exc}") from exc
        if resp.status_code != 200:
            detail = resp.text[:200]
            raise VertexAuthError(f"Google refused the service-account key ({resp.status_code}): {detail}")
        body = resp.json()
        token = body["access_token"]
        self._tokens[cache_key] = (token, now + int(body.get("expires_in", _LIFETIME)))
        return token

    def cached(self, raw_key: str) -> str:
        """The token from the last `token` call for this key ("" if none), for the synchronous header hook."""
        try:
            key = ServiceAccountKey(raw_key)
        except VertexAuthError:
            return ""
        return self._tokens.get(f"{key.email}:{key.key_id}", ("", 0.0))[0]
