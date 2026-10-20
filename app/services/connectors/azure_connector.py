"""Azure OpenAI (Microsoft Foundry): your own deployments on your own Azure resource (calls: azure_client)."""

from app.services.connectors.base import ConnectorConfigField, ConnectorDefinition

AZURE_CONNECTOR = ConnectorDefinition(
    id="azure",
    engine_name="azure",
    display_name="Azure OpenAI",
    description=(
        "Models you deployed on your own Azure OpenAI or Microsoft Foundry resource: OpenAI models such as GPT-4.1 "
        "and GPT-5, and Foundry models such as DeepSeek, Grok, Llama and Mistral. Billed to your Azure subscription. "
        "Chats use the deployments you list below; embedding deployments power the knowledge base. Text only for now "
        "(no images or tools)."
    ),
    config_fields=(
        ConnectorConfigField(
            name="endpoint",
            label="Endpoint",
            field_type="text",
            help_text=(
                "Your resource's endpoint from the Azure portal (Keys and Endpoint), e.g. "
                "https://my-resource.openai.azure.com or https://my-resource.services.ai.azure.com."
            ),
        ),
        ConnectorConfigField(
            name="api_key",
            label="API key",
            field_type="password",
            secret=True,
            help_text="KEY 1 or KEY 2 from the same Keys and Endpoint page.",
        ),
        ConnectorConfigField(
            name="deployments",
            label="Chat deployments",
            field_type="text",
            help_text=(
                "Your deployment names (not model names), comma separated, e.g. gpt-4.1-mini, DeepSeek-V3. Azure calls "
                "models by deployment, and its API doesn't list them, so they are entered here."
            ),
        ),
        ConnectorConfigField(
            name="embedding_deployments",
            label="Embedding deployments",
            field_type="text",
            required=False,
            help_text="Optional: embedding deployments for the knowledge base, e.g. text-embedding-3-small.",
        ),
    ),
)
