"""Azure OpenAI / Microsoft Foundry through its v1 API (`<endpoint>/openai/v1`, OpenAI-compatible, no api-version):
https://learn.microsoft.com/azure/foundry/openai/api-version-lifecycle. The key goes in an `api-key` header and
`model` is a deployment name. Azure's /models lists the models a region offers, not your deployments, so the models
are the deployment names saved on the Connectors page; /models only checks the endpoint and key."""

from collections.abc import AsyncGenerator

import httpx

from app.services import connector_config_cache
from app.services.openai_compatible import OpenAICompatibleProvider

# Reasoning deployments (o-series, GPT-5) refuse these; a deployment that does is retried, and remembered, without them.
_SAMPLING_FIELDS = ("temperature", "top_p", "seed")


class AzureError(Exception):
    """Azure OpenAI is unreachable, refused the call, or isn't configured and enabled on the Connectors page."""


class AzureProvider(OpenAICompatibleProvider):
    connector_id = "azure"
    name = "Azure OpenAI"
    key_help = "copy KEY 1 from your resource's Keys and Endpoint page in the Azure portal."
    error_type = AzureError

    def __init__(self) -> None:
        self._no_sampling: set[str] = set()

    @staticmethod
    def api_base(config: dict[str, str]) -> str:
        """`<endpoint>/openai/v1`, whether the endpoint was pasted with or without that path."""
        endpoint = config.get("endpoint", "").strip().rstrip("/")
        for suffix in ("/openai/v1", "/openai"):
            endpoint = endpoint.removesuffix(suffix)
        return f"{endpoint}/openai/v1"

    @property
    def base_url(self) -> str:  # type: ignore[override]
        return self.api_base(connector_config_cache.get_config(self.connector_id))

    def headers(self, config: dict[str, str]) -> dict[str, str]:
        return {"api-key": config.get("api_key", "").strip()}

    @staticmethod
    def _names(value: str) -> list[str]:
        return [name.strip() for name in value.split(",") if name.strip()]

    async def list_models(self) -> list[dict]:
        config = self.live_config()
        chat = [{"name": n, "capabilities": ["completion"], "display_name": n, "vendor": self.name}
                for n in self._names(config.get("deployments", ""))]  # fmt: skip
        embed = [{"name": n, "capabilities": ["embedding"], "display_name": n, "vendor": self.name}
                 for n in self._names(config.get("embedding_deployments", ""))]  # fmt: skip
        return sorted(chat + embed, key=lambda m: m["name"])

    async def _get_models(self, config: dict[str, str], timeout: httpx.Timeout) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(f"{self.api_base(config)}/models", headers=self.headers(config))

    def chat_payload(self, model: str, messages: list[dict], params: dict, *, stream: bool) -> dict:
        payload = super().chat_payload(model, messages, params, stream=stream)
        if model in self._no_sampling:
            for name in _SAMPLING_FIELDS:
                payload.pop(name, None)
        return payload

    async def chat_stream(self, model: str, messages: list[dict], params: dict) -> AsyncGenerator[str, None]:
        sent = False
        try:
            async for chunk in super().chat_stream(model, messages, params):
                sent = True
                yield chunk
            return
        except AzureError as exc:
            # Only before any text, so nothing is sent twice.
            if sent or model in self._no_sampling or "unsupported" not in str(exc).lower():
                raise
            self._no_sampling.add(model)
        async for chunk in super().chat_stream(model, messages, params):
            yield chunk

    def explain(self, exc: Exception, model: str) -> Exception | None:
        text = str(exc)
        if "(401)" in text or "(403)" in text:
            return AzureError("Azure rejected the API key. Check KEY 1 on the Connectors page.")
        if "(404)" in text:
            return AzureError(
                f'Azure has no deployment named "{model}" on this resource. Check the deployment names on the '
                "Connectors page (they are the names you gave when deploying, not the model names)."
            )
        if "(429)" in text:
            return AzureError("Azure's rate limit or quota for this deployment was reached. Wait a moment, or raise "
                              "the deployment's tokens-per-minute limit in the Azure portal.")  # fmt: skip
        return None

    async def test_connection(self, config: dict[str, str]) -> tuple[bool, str]:
        """Checks the endpoint and key (GET /models) and that at least one chat deployment is listed."""
        if not config.get("endpoint", "").strip().startswith("https://"):
            return False, "Enter your resource's endpoint, starting with https://."
        if not self._names(config.get("deployments", "")):
            return False, "Enter at least one chat deployment name."
        ok, message = await super().test_connection(config)
        if not ok and "HTTP 404" in message:
            return False, "Azure answered 404: check that the endpoint is your resource's endpoint."
        return ok, message


PROVIDER = AzureProvider()
