"""Tests for Google Vertex AI (vertex_auth, vertex_client). A real RSA key is generated so the signed JWT can be
verified; Google's token service and Vertex are httpx.MockTransport fakes (no network)."""

import base64
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services import connector_config_cache, vertex_client
from app.services.vertex_auth import SCOPE, ServiceAccountKey, VertexAuthError, VertexTokenSource
from app.services.vertex_client import VertexError, VertexProvider

REAL_CLIENT = httpx.AsyncClient
PARAMS = {"temperature": 0.5, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_predict": 64, "seed": 7}
SSE = 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = PRIVATE.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
KEY_JSON = json.dumps(
    {
        "type": "service_account",
        "project_id": "my-proj",
        "private_key_id": "kid1",
        "private_key": PEM,
        "client_email": "bot@my-proj.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)
CONFIG = {"service_account_json": KEY_JSON, "location": "", "project_id": "", "models": "google/gemini-2.5-flash"}


@pytest.fixture(autouse=True)
def ready():
    connector_config_cache._cache = {
        "vertex": {"config": dict(CONFIG), "enabled": True, "configured": True, "last_test_passed": True}
    }
    vertex_client.PROVIDER.tokens = VertexTokenSource()
    yield
    connector_config_cache._cache = {}


def _fake_google(monkeypatch, chat_status: int = 200) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        if chat_status != 200:
            return httpx.Response(chat_status, json={"error": {"message": "nope"}})
        return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return seen


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_the_assertion_is_a_jwt_signed_by_the_key():
    jwt = ServiceAccountKey(KEY_JSON).assertion(now=1000)
    header, claims, signature = jwt.split(".")
    PRIVATE.public_key().verify(_unb64(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    assert json.loads(_unb64(header)) == {"alg": "RS256", "typ": "JWT", "kid": "kid1"}
    assert json.loads(_unb64(claims)) == {
        "iss": "bot@my-proj.iam.gserviceaccount.com",
        "scope": SCOPE,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": 1000,
        "exp": 4600,
    }


def test_a_bad_key_is_reported_clearly():
    with pytest.raises(VertexAuthError, match="isn't a valid JSON key"):
        ServiceAccountKey("{not json")


@pytest.mark.asyncio
async def test_the_token_is_cached_and_renewed_near_its_end(monkeypatch):
    seen = _fake_google(monkeypatch)
    source = VertexTokenSource()
    assert await source.token(KEY_JSON) == "tok-1"
    assert await source.token(KEY_JSON) == "tok-1"
    assert len(seen) == 1 and b"jwt-bearer" in seen[0].content
    cache_key = next(iter(source._tokens))
    source._tokens[cache_key] = ("old", time.time() + 60)  # less than 5 minutes left
    assert await source.token(KEY_JSON) == "tok-1" and len(seen) == 2


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (
            {},
            "https://us-central1-aiplatform.googleapis.com/v1/projects/my-proj/locations/us-central1/endpoints/openapi",
        ),
        (
            {"location": "europe-west4", "project_id": "other"},
            "https://europe-west4-aiplatform.googleapis.com/v1/projects/other/locations/europe-west4/endpoints/openapi",
        ),
        (
            {"location": "global"},
            "https://aiplatform.googleapis.com/v1/projects/my-proj/locations/global/endpoints/openapi",
        ),
    ],
)
def test_the_endpoint_follows_project_and_location(overrides, expected):
    assert VertexProvider.api_base({**CONFIG, **overrides}) == expected


@pytest.mark.asyncio
async def test_models_are_the_saved_names():
    models = await vertex_client.PROVIDER.list_models()
    assert [(m["name"], m["capabilities"]) for m in models] == [("google/gemini-2.5-flash", ["completion"])]


@pytest.mark.asyncio
async def test_chat_signs_in_then_calls_vertex_with_the_token(monkeypatch):
    seen = _fake_google(monkeypatch)

    reply = await vertex_client.PROVIDER.chat_once(
        "google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], PARAMS
    )

    assert reply == "Hi"
    token_call, chat_call = seen
    assert token_call.url.host == "oauth2.googleapis.com"
    assert str(chat_call.url).endswith("/projects/my-proj/locations/us-central1/endpoints/openapi/chat/completions")
    assert chat_call.headers["authorization"] == "Bearer tok-1"
    assert json.loads(chat_call.content)["model"] == "google/gemini-2.5-flash"


@pytest.mark.asyncio
async def test_a_missing_model_gets_a_clear_message(monkeypatch):
    _fake_google(monkeypatch, chat_status=404)
    with pytest.raises(VertexError, match='no model "google/nope"'):
        await vertex_client.PROVIDER.chat_once("google/nope", [{"role": "user", "content": "hi"}], PARAMS)


@pytest.mark.asyncio
async def test_test_connection(monkeypatch):
    provider = vertex_client.PROVIDER
    assert (await provider.test_connection({**CONFIG, "service_account_json": ""}))[0] is False
    assert (await provider.test_connection({**CONFIG, "models": " "}))[0] is False
    assert "valid JSON key" in (await provider.test_connection({**CONFIG, "service_account_json": "x"}))[1]

    _fake_google(monkeypatch, chat_status=403)
    ok, message = await provider.test_connection(CONFIG)
    assert not ok and "Vertex AI User role" in message

    seen = _fake_google(monkeypatch)
    assert await provider.test_connection(CONFIG) == (True, "Connected: google/gemini-2.5-flash answered.")
    assert json.loads(seen[-1].content)["max_tokens"] == 1


@pytest.mark.asyncio
async def test_health_only_signs_in(monkeypatch):
    seen = _fake_google(monkeypatch)
    assert await vertex_client.PROVIDER.check_health() == {"vertex": True}
    assert [r.url.host for r in seen] == ["oauth2.googleapis.com"]
