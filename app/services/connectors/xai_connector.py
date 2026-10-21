"""xAI: the Grok models (calls: xai_client). Not to be confused with Groq (groq_connector)."""

from app.services.connectors.base import ConnectorConfigField, ConnectorDefinition

XAI_CONNECTOR = ConnectorDefinition(
    id="xai",
    engine_name="xai",
    display_name="xAI Grok",
    description=(
        "xAI's Grok models, from fast low-cost ones to large reasoning models, billed per use to your xAI account. "
        "Chat only: no embedding models, so the knowledge base can't be used while xAI is the active engine. "
        "Text only for now (no images or tools)."
    ),
    config_fields=(
        ConnectorConfigField(
            name="api_key",
            label="API key",
            field_type="password",
            secret=True,
            help_text="Create one in the xAI console (console.x.ai > API keys). It starts with xai-.",
        ),
    ),
)
