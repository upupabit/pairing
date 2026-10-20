"""BedrockEngine: InferenceEngine adapter over bedrock_client.PROVIDER (openai_compatible_engine)."""

from app.services import bedrock_client
from app.services.bedrock_client import BedrockError
from app.services.engines.openai_compatible_engine import OpenAICompatibleEngine, cloud_capabilities


class BedrockEngine(OpenAICompatibleEngine):
    name = "bedrock"
    display_name = "Amazon Bedrock"
    capabilities = cloud_capabilities(embeddings=False)
    error_types = (BedrockError,)
    provider = bedrock_client.PROVIDER
    usage_note = "Usage and cost are in the AWS console (Bedrock's model invocation metrics, and Billing)."
