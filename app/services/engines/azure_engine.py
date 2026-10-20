"""AzureEngine: InferenceEngine adapter over azure_client.PROVIDER (openai_compatible_engine)."""

from app.services import azure_client
from app.services.azure_client import AzureError
from app.services.engines.openai_compatible_engine import OpenAICompatibleEngine, cloud_capabilities


class AzureEngine(OpenAICompatibleEngine):
    name = "azure"
    display_name = "Azure OpenAI"
    capabilities = cloud_capabilities(embeddings=True)
    error_types = (AzureError,)
    provider = azure_client.PROVIDER
    usage_note = "Usage and cost are in the Azure portal (your resource's Metrics, and Cost Management)."
