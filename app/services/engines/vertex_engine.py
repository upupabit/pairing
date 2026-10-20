"""VertexEngine: InferenceEngine adapter over vertex_client.PROVIDER (openai_compatible_engine)."""

from app.services import vertex_client
from app.services.engines.openai_compatible_engine import OpenAICompatibleEngine, cloud_capabilities
from app.services.vertex_client import VertexError


class VertexEngine(OpenAICompatibleEngine):
    name = "vertex"
    display_name = "Google Vertex AI"
    capabilities = cloud_capabilities(embeddings=False)
    error_types = (VertexError,)
    provider = vertex_client.PROVIDER
    usage_note = "Usage and cost are in the Google Cloud console (Vertex AI dashboard, and Billing)."
