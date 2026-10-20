"""Google Vertex AI through its OpenAI-compatible Chat Completions endpoint
(`.../v1/projects/<project>/locations/<location>/endpoints/openapi`), signed in with a service-account key
(vertex_auth). https://docs.cloud.google.com/vertex-ai/generative-ai/docs/migrate/openai/auth-and-credentials

The models are the names saved on the Connectors page: there is no model list on this endpoint."""

from collections.abc import AsyncGenerator

import httpx

from app.services import connector_config_cache
from app.services.openai_compatible import HEALTH_TIMEOUT, OpenAICompatibleProvider
from app.services.vertex_auth import ServiceAccountKey, VertexAuthError, VertexTokenSource

_DEFAULT_LOCATION = "us-central1"


class VertexError(Exception):
    """Vertex AI is unreachable, refused the call, or isn't configured and enabled on the Connectors page."""


class VertexProvider(OpenAICompatibleProvider):
    connector_id = "vertex"
    name = "Google Vertex AI"
    key_help = "use a JSON key of a service account with the Vertex AI User role."
    error_type = VertexError

    def __init__(self) -> None:
        self.tokens = VertexTokenSource()

    @staticmethod
    def api_base(config: dict[str, str]) -> str:
        location = config.get("location", "").strip() or _DEFAULT_LOCATION
        project = config.get("project_id", "").strip()
        if not project:
            try:
                project = ServiceAccountKey(config.get("service_account_json", "")).project_id
            except VertexAuthError:
                project = ""
        host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
        return f"https://{host}/v1/projects/{project}/locations/{location}/endpoints/openapi"

    @property
    def base_url(self) -> str:  # type: ignore[override]
        return self.api_base(connector_config_cache.get_config(self.connector_id))

    def headers(self, config: dict[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.cached(config.get('service_account_json', ''))}"}

    async def _sign_in(self, config: dict[str, str]) -> None:
        try:
            await self.tokens.token(config.get("service_account_json", ""))
        except VertexAuthError as exc:
            raise VertexError(str(exc)) from exc

    @staticmethod
    def _names(value: str) -> list[str]:
        return [name.strip() for name in value.split(",") if name.strip()]

    async def list_models(self) -> list[dict]:
        config = self.live_config()
        return [
            {"name": n, "capabilities": ["completion"], "display_name": n.split("/")[-1], "vendor": self.name}
            for n in sorted(self._names(config.get("models", "")))
        ]

    async def chat_stream(self, model: str, messages: list[dict], params: dict) -> AsyncGenerator[str, None]:
        await self._sign_in(self.live_config())
        async for chunk in super().chat_stream(model, messages, params):
            yield chunk

    def explain(self, exc: Exception, model: str) -> Exception | None:
        text = str(exc)
        if "(401)" in text or "(403)" in text:
            return VertexError(
                "Vertex AI refused the request: check that the Vertex AI API is enabled in the project and that the "
                "service account has the Vertex AI User role."
            )
        if "(404)" in text:
            return VertexError(
                f'Vertex AI has no model "{model}" in this project and location. Check its name (e.g. '
                "google/gemini-2.5-flash), the location, and for partner models that they are enabled in Model Garden."
            )
        if "(429)" in text:
            return VertexError("Vertex AI's quota for this model was reached. Wait a moment, or request more quota.")
        return None

    async def test_connection(self, config: dict[str, str]) -> tuple[bool, str]:
        """Signs in, then asks the first model for one token: checks the key, project, location and model at once."""
        models = self._names(config.get("models", ""))
        if not config.get("service_account_json", "").strip():
            return False, "Paste the service account's JSON key."
        if not models:
            return False, "Enter at least one model, e.g. google/gemini-2.5-flash."
        try:
            token = await self.tokens.token(config["service_account_json"])
        except VertexAuthError as exc:
            return False, str(exc)
        body = {"model": models[0], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        try:
            async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.api_base(config)}/chat/completions", json=body, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as exc:
            return False, f"Could not reach Vertex AI: {exc}"
        if resp.status_code == 200:
            return True, f"Connected: {models[0]} answered."
        clearer = self.explain(VertexError(f"({resp.status_code})"), models[0])
        return False, str(clearer) if clearer else f"Vertex AI returned HTTP {resp.status_code}: {resp.text[:200]}"

    async def check_health(self) -> dict[str, bool]:
        """Reachable when the saved key still signs in (no model call, so no cost)."""
        if not connector_config_cache.is_ready(self.connector_id):
            return {self.connector_id: False}
        try:
            await self._sign_in(connector_config_cache.get_config(self.connector_id))
            return {self.connector_id: True}
        except VertexError:
            return {self.connector_id: False}


PROVIDER = VertexProvider()
