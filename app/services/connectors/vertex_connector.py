"""Google Vertex AI: Gemini and partner models on your own Google Cloud project (calls: vertex_client)."""

from app.services.connectors.base import ConnectorConfigField, ConnectorDefinition

VERTEX_CONNECTOR = ConnectorDefinition(
    id="vertex",
    engine_name="vertex",
    display_name="Google Vertex AI",
    description=(
        "Gemini and partner models (Llama, DeepSeek, Qwen and more) on your own Google Cloud project, billed to it, "
        "with your project's data and region controls. Unlike the Google Gemini connector, it signs in with a "
        "service-account key. Text only for now (no images, tools or embeddings)."
    ),
    config_fields=(
        ConnectorConfigField(
            name="service_account_json",
            label="Service-account key (JSON)",
            field_type="password",
            secret=True,
            help_text=(
                "In Google Cloud, IAM > Service accounts: a service account with the Vertex AI User role, then "
                "Keys > Add key > JSON. Paste the whole file. The Vertex AI API must be enabled in the project."
            ),
        ),
        ConnectorConfigField(
            name="project_id",
            label="Project ID",
            field_type="text",
            required=False,
            help_text="Leave blank to use the project the key belongs to.",
        ),
        ConnectorConfigField(
            name="location",
            label="Location",
            field_type="text",
            required=False,
            help_text="A region such as us-central1 or europe-west4, or global. Leave blank for us-central1.",
        ),
        ConnectorConfigField(
            name="models",
            label="Models",
            field_type="text",
            help_text=(
                "Comma separated, as Vertex names them, e.g. google/gemini-2.5-flash, google/gemini-2.5-pro. "
                "Partner models need to be enabled in Model Garden first."
            ),
        ),
    ),
)
