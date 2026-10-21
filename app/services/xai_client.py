"""xAI (https://api.x.ai/v1): the Grok models through the OpenAI-compatible Chat Completions API, Bearer API key.
xAI recommends its newer Responses API for new work but keeps Chat Completions documented and supported; it covers
this app's text chat. https://docs.x.ai/developers/rest-api-reference/inference/chat-completions

Models come from GET /v1/language-models (chat and image-understanding models only, unlike /v1/models), read
defensively since only its fields, not its exact layout, are documented."""

from app.services.model_names import ReadableModelName
from app.services.openai_compatible import OpenAICompatibleProvider


class XaiError(Exception):
    """xAI is unreachable, refused the call, or isn't configured and enabled on the Connectors page."""


class XaiProvider(OpenAICompatibleProvider):
    connector_id = "xai"
    name = "xAI"
    base_url = "https://api.x.ai/v1"
    models_url = "https://api.x.ai/v1/language-models"
    key_help = "create one in the xAI console (console.x.ai > API keys)."
    error_type = XaiError

    def model_entries(self, body: dict) -> list[dict]:
        return body.get("models") or body.get("data") or []

    def model_info(self, entry: dict) -> dict | None:
        model_id = entry.get("id", "")
        outputs = entry.get("output_modalities")
        if not model_id or (outputs is not None and "text" not in outputs):
            return None  # e.g. an image-generation model
        readable = ReadableModelName(model_id, fallback_vendor="xAI")
        return {
            "name": model_id,
            "capabilities": ["completion"],
            "display_name": readable.display_name,
            "vendor": "xAI",
            "details": {"context_length": entry.get("context_length")},
        }

    def explain(self, exc: Exception, model: str) -> Exception | None:
        text = str(exc)
        if "(402)" in text or "(403)" in text:
            return XaiError("xAI refused the request: the account may have no credits left. Check console.x.ai.")
        if "(404)" in text:
            return XaiError(f"xAI has no model {model} for this key. Pick another model.")
        if "(429)" in text:
            return XaiError("xAI's rate limit for this model was reached. Wait a moment.")
        return None


PROVIDER = XaiProvider()
