"""Amazon Bedrock: models on your own AWS account (calls: bedrock_client)."""

from app.services.connectors.base import ConnectorConfigField, ConnectorDefinition

BEDROCK_CONNECTOR = ConnectorDefinition(
    id="bedrock",
    engine_name="bedrock",
    display_name="Amazon Bedrock",
    description=(
        "Models on your own AWS account through Bedrock's OpenAI-compatible API: OpenAI's GPT-OSS, Anthropic Claude, "
        "Meta Llama, Mistral, DeepSeek, Qwen and more, billed to your AWS account. Sign in with a Bedrock API key, or "
        "with an IAM access key (recommended for long-term use). Text only for now (no images, tools or embeddings)."
    ),
    config_fields=(
        ConnectorConfigField(
            name="region",
            label="Region",
            field_type="text",
            help_text="The AWS Region to use, e.g. us-east-1 or eu-central-1.",
        ),
        ConnectorConfigField(
            name="api_key",
            label="Bedrock API key",
            field_type="password",
            required=False,
            secret=True,
            help_text=(
                "Either this: a long-term key from the Bedrock console (API keys), made in the Region above. AWS "
                "recommends these for trying things out. Or leave it blank and use an access key below."
            ),
        ),
        ConnectorConfigField(
            name="access_key_id",
            label="Access key ID",
            field_type="text",
            required=False,
            help_text=(
                "Or this: an IAM user's access key with Bedrock permissions (bedrock:InvokeModel and "
                "bedrock:InvokeModelWithResponseStream). Each request is signed with it (SigV4)."
            ),
        ),
        ConnectorConfigField(
            name="secret_access_key",
            label="Secret access key",
            field_type="password",
            required=False,
            secret=True,
            help_text="The secret that goes with the access key ID.",
        ),
        ConnectorConfigField(
            name="models",
            label="Models",
            field_type="text",
            help_text=(
                "Model IDs or inference profile IDs, comma separated, e.g. openai.gpt-oss-120b-1:0, "
                "us.anthropic.claude-sonnet-4-6. Use models whose model card lists Chat Completions."
            ),
        ),
    ),
)
