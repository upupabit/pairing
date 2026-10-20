"""Tests for Amazon Bedrock (aws_sigv4, bedrock_client). Bedrock is an httpx.MockTransport fake (no network)."""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.services import bedrock_client, connector_config_cache
from app.services.aws_sigv4 import SigV4Signer
from app.services.bedrock_client import BedrockError, BedrockProvider

REAL_CLIENT = httpx.AsyncClient
PARAMS = {"temperature": 0.5, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1, "num_predict": 64, "seed": 7}
SSE = 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
KEY_CONFIG = {"region": "us-east-1", "api_key": "brk-key", "models": "openai.gpt-oss-120b-1:0"}
IAM_CONFIG = {
    "region": "eu-central-1",
    "access_key_id": "AKIDEXAMPLE",
    "secret_access_key": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
    "models": "us.anthropic.claude-sonnet-4-6",
}


def _use(config: dict) -> None:
    connector_config_cache._cache = {
        "bedrock": {"config": dict(config), "enabled": True, "configured": True, "last_test_passed": True}
    }


@pytest.fixture(autouse=True)
def ready():
    _use(KEY_CONFIG)
    bedrock_client.PROVIDER._dropped.clear()
    yield
    connector_config_cache._cache = {}


def _fake_bedrock(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(record), **kw))
    return seen


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})


def test_the_signing_key_matches_awss_published_example():
    signer = SigV4Signer("AKID", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "us-east-1", "iam")
    assert signer.signing_key("20120215").hex() == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"


def test_the_signature_covers_the_exact_body():
    signer = SigV4Signer("AKIDEXAMPLE", "secret", "us-east-1")
    when = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    url = "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1/chat/completions"
    headers = signer.headers(url, b'{"a":1}', now=when)
    assert headers["X-Amz-Date"] == "20261020T120000Z"
    assert headers["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261020/us-east-1/bedrock/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date, Signature="
    )
    # Recomputed independently from the published steps.
    canonical = "\n".join([
        "POST", "/openai/v1/chat/completions", "",
        "content-type:application/json\nhost:bedrock-runtime.us-east-1.amazonaws.com\nx-amz-date:20261020T120000Z\n",
        "content-type;host;x-amz-date", hashlib.sha256(b'{"a":1}').hexdigest(),
    ])  # fmt: skip
    to_sign = "\n".join([
        "AWS4-HMAC-SHA256", "20261020T120000Z", "20261020/us-east-1/bedrock/aws4_request",
        hashlib.sha256(canonical.encode()).hexdigest(),
    ])  # fmt: skip
    expected = hmac.new(signer.signing_key("20261020"), to_sign.encode(), hashlib.sha256).hexdigest()
    assert headers["Authorization"].endswith(f"Signature={expected}")
    assert signer.headers(url, b'{"a":2}', now=when)["Authorization"] != headers["Authorization"]


@pytest.mark.asyncio
async def test_an_api_key_is_sent_as_bearer(monkeypatch):
    seen = _fake_bedrock(monkeypatch, _ok)

    assert await bedrock_client.PROVIDER.chat_once("openai.gpt-oss-120b-1:0", [{"role": "user", "content": "hi"}],
                                                   PARAMS) == "Hi"  # fmt: skip

    [request] = seen
    assert str(request.url) == "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer brk-key"
    assert json.loads(request.content)["model"] == "openai.gpt-oss-120b-1:0"


@pytest.mark.asyncio
async def test_an_access_key_signs_the_exact_bytes_sent(monkeypatch):
    _use(IAM_CONFIG)
    seen = _fake_bedrock(monkeypatch, _ok)

    await bedrock_client.PROVIDER.chat_once(
        "us.anthropic.claude-sonnet-4-6", [{"role": "user", "content": "hi"}], PARAMS
    )

    [request] = seen
    assert request.url.host == "bedrock-runtime.eu-central-1.amazonaws.com"
    auth = request.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/") and "/eu-central-1/bedrock/" in auth
    when = datetime.strptime(request.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    resigned = SigV4Signer("AKIDEXAMPLE", IAM_CONFIG["secret_access_key"], "eu-central-1").headers(
        str(request.url), request.content, now=when
    )
    assert resigned["Authorization"] == auth


@pytest.mark.asyncio
async def test_a_refused_sampling_setting_is_dropped_step_by_step(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        if "top_p" in body:
            return httpx.Response(400, json={"message": "temperature and top_p cannot both be specified"})
        return _ok(request)

    seen = _fake_bedrock(monkeypatch, handler)

    assert await bedrock_client.PROVIDER.chat_once("m", [{"role": "user", "content": "hi"}], PARAMS) == "Hi"
    assert len(seen) == 2
    last = json.loads(seen[-1].content)
    assert "top_p" not in last and "seed" not in last and last["temperature"] == 0.5
    await bedrock_client.PROVIDER.chat_once("m", [{"role": "user", "content": "hi"}], PARAMS)
    assert len(seen) == 3  # remembered


@pytest.mark.asyncio
async def test_errors_are_explained(monkeypatch):
    _fake_bedrock(monkeypatch, lambda r: httpx.Response(404, json={"message": "not found"}))
    with pytest.raises(BedrockError, match='no model "x"'):
        await bedrock_client.PROVIDER.chat_once("x", [{"role": "user", "content": "hi"}], PARAMS)
    _fake_bedrock(
        monkeypatch, lambda r: httpx.Response(403, json={"message": "Credential should be scoped to a valid region"})
    )
    with pytest.raises(BedrockError, match="another AWS Region"):
        await bedrock_client.PROVIDER.chat_once("x", [{"role": "user", "content": "hi"}], PARAMS)


@pytest.mark.asyncio
async def test_test_connection(monkeypatch):
    provider = bedrock_client.PROVIDER
    assert (await provider.test_connection({**KEY_CONFIG, "region": ""}))[1].startswith("Enter the AWS Region")
    assert "API key, or an access key" in (await provider.test_connection({"region": "us-east-1", "models": "m"}))[1]
    assert (await provider.test_connection({**KEY_CONFIG, "models": ""}))[0] is False

    _fake_bedrock(monkeypatch, lambda r: httpx.Response(403, json={"message": "AccessDenied"}))
    ok, message = await provider.test_connection(KEY_CONFIG)
    assert not ok and "AWS refused" in message

    seen = _fake_bedrock(monkeypatch, lambda r: httpx.Response(200, json={"choices": []}))
    assert await provider.test_connection(IAM_CONFIG) == (True, "Connected: us.anthropic.claude-sonnet-4-6 answered.")
    assert json.loads(seen[0].content)["max_tokens"] == 1 and "AWS4-HMAC-SHA256" in seen[0].headers["authorization"]


@pytest.mark.asyncio
async def test_models_are_the_saved_ids_and_health_makes_no_call(monkeypatch):
    seen = _fake_bedrock(monkeypatch, _ok)
    assert [m["name"] for m in await bedrock_client.PROVIDER.list_models()] == ["openai.gpt-oss-120b-1:0"]
    assert await bedrock_client.PROVIDER.check_health() == {"bedrock": True}
    assert seen == []
    assert BedrockProvider.api_base({"region": "ap-south-1"}).endswith("ap-south-1.amazonaws.com/openai/v1")
