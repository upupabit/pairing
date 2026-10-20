"""Amazon Bedrock through the OpenAI-compatible Chat Completions API of its recommended bedrock-runtime endpoint
(`https://bedrock-runtime.<region>.amazonaws.com/openai/v1`):
https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html

Signs in with a Bedrock API key (Bearer; AWS calls long-term keys "for exploration") or an IAM access key, each
request signed with SigV4 (aws_sigv4). bedrock-runtime has no GET /models, so the models are the IDs saved on the
Connectors page."""

import json
from collections.abc import AsyncGenerator

import httpx

from app.services import connector_config_cache
from app.services.aws_sigv4 import SigV4Signer
from app.services.openai_compat import OpenAIChatStream
from app.services.openai_compatible import CHAT_TIMEOUT, HEALTH_TIMEOUT, OpenAICompatibleProvider

# What a model that refuses a sampling setting is retried without, in order (e.g. newer Claude models refuse
# temperature and top_p together; some refuse seed).
_DROP_STEPS = (("top_p", "seed"), ("temperature",))


class BedrockError(Exception):
    """Amazon Bedrock is unreachable, refused the call, or isn't configured and enabled on the Connectors page."""


class BedrockProvider(OpenAICompatibleProvider):
    connector_id = "bedrock"
    name = "Amazon Bedrock"
    error_type = BedrockError

    def __init__(self) -> None:
        self._dropped: dict[str, int] = {}  # model -> how many _DROP_STEPS it needs

    @staticmethod
    def api_base(config: dict[str, str]) -> str:
        return f"https://bedrock-runtime.{config.get('region', '').strip()}.amazonaws.com/openai/v1"

    @staticmethod
    def credentials_problem(config: dict[str, str]) -> str | None:
        if not config.get("region", "").strip():
            return "Enter the AWS Region, e.g. us-east-1."
        has_key = bool(config.get("api_key", "").strip())
        has_iam = bool(config.get("access_key_id", "").strip() and config.get("secret_access_key", "").strip())
        if not (has_key or has_iam):
            return "Enter a Bedrock API key, or an access key ID and secret access key."
        return None

    def auth_headers(self, config: dict[str, str], url: str, body: bytes) -> dict[str, str]:
        api_key = config.get("api_key", "").strip()
        if api_key:
            return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        signer = SigV4Signer(
            config["access_key_id"].strip(), config["secret_access_key"].strip(), config["region"].strip()
        )
        return signer.headers(url, body)

    @staticmethod
    def _names(value: str) -> list[str]:
        return [name.strip() for name in value.split(",") if name.strip()]

    async def list_models(self) -> list[dict]:
        config = self.live_config()
        return [
            {"name": n, "capabilities": ["completion"], "display_name": n, "vendor": self.name}
            for n in sorted(self._names(config.get("models", "")))
        ]

    def chat_payload(self, model: str, messages: list[dict], params: dict, *, stream: bool) -> dict:
        payload = super().chat_payload(model, messages, params, stream=stream)
        for step in _DROP_STEPS[: self._dropped.get(model, 0)]:
            for name in step:
                payload.pop(name, None)
        return payload

    async def _stream_once(self, model: str, messages: list[dict], params: dict) -> AsyncGenerator[str, None]:
        config = self.live_config()
        payload = self.chat_payload(model, messages, params, stream=True)
        body = json.dumps(payload).encode()
        url = f"{self.api_base(config)}/chat/completions"
        async for chunk in OpenAIChatStream(self.name, self.error_type).stream(
            url, payload, self.auth_headers(config, url, body), CHAT_TIMEOUT, body=body
        ):
            yield chunk

    async def chat_stream(self, model: str, messages: list[dict], params: dict) -> AsyncGenerator[str, None]:
        while True:
            sent = False
            try:
                async for chunk in self._stream_once(model, messages, params):
                    sent = True
                    yield chunk
                return
            except BedrockError as exc:
                text = str(exc).lower()
                retry = not sent and "(400)" in text and self._dropped.get(model, 0) < len(_DROP_STEPS)
                if retry and any(name in text for name in ("temperature", "top_p", "seed")):
                    self._dropped[model] = self._dropped.get(model, 0) + 1  # before any text: safe to retry
                    continue
                clearer = self.explain(exc, model)
                if clearer is None:
                    raise
                raise clearer from exc

    def explain(self, exc: Exception, model: str) -> Exception | None:
        text = str(exc)
        if "scoped to a valid region" in text:
            return BedrockError("This Bedrock API key belongs to another AWS Region: use the Region it was made in.")
        if "(401)" in text or "(403)" in text:
            return BedrockError(
                "AWS refused the request: check the key, that it allows Bedrock (bedrock:InvokeModel and "
                f"bedrock:InvokeModelWithResponseStream), and that {model} is available in this Region."
            )
        if "(404)" in text or "isn't supported" in text:
            return BedrockError(
                f'Bedrock has no model "{model}" for Chat Completions here. Check the model ID (or inference profile '
                "ID, e.g. us.…) and that its model card lists Chat Completions on bedrock-runtime."
            )
        if "(429)" in text:
            return BedrockError("Bedrock's quota for this model was reached. Wait a moment, or request more quota.")
        return None

    async def test_connection(self, config: dict[str, str]) -> tuple[bool, str]:
        """Asks the first model for one token: checks the Region, credentials, permissions and model at once."""
        problem = self.credentials_problem(config)
        models = self._names(config.get("models", ""))
        if problem or not models:
            return False, problem or "Enter at least one model ID, e.g. openai.gpt-oss-120b-1:0."
        url = f"{self.api_base(config)}/chat/completions"
        body = json.dumps({"model": models[0], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT) as client:
                resp = await client.post(
                    url, content=body.encode(), headers=self.auth_headers(config, url, body.encode())
                )
        except httpx.HTTPError as exc:
            return False, f"Could not reach Bedrock: {exc}"
        if resp.status_code == 200:
            return True, f"Connected: {models[0]} answered."
        clearer = self.explain(BedrockError(f"({resp.status_code}) {resp.text[:300]}"), models[0])
        return False, str(clearer) if clearer else f"Bedrock returned HTTP {resp.status_code}: {resp.text[:200]}"

    async def check_health(self) -> dict[str, bool]:
        """Ready means set up and tested: bedrock-runtime has no free call to probe (no GET /models)."""
        return {self.connector_id: connector_config_cache.is_ready(self.connector_id)}


PROVIDER = BedrockProvider()
