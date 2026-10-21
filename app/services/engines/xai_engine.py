"""XaiEngine: InferenceEngine adapter over xai_client.PROVIDER (openai_compatible_engine)."""

from app.services import xai_client
from app.services.engines.openai_compatible_engine import OpenAICompatibleEngine, cloud_capabilities
from app.services.xai_client import XaiError


class XaiEngine(OpenAICompatibleEngine):
    name = "xai"
    display_name = "xAI Grok"
    capabilities = cloud_capabilities(embeddings=False)
    error_types = (XaiError,)
    provider = xai_client.PROVIDER
    usage_note = "xAI has no usage API for this: see your usage and credits in the xAI console (console.x.ai)."
