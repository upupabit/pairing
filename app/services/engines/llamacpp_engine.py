"""LlamaCppEngine: InferenceEngine adapter over llamacpp_client/llamacpp_admin/llamacpp_pool. Forwards by module
reference, looked up per call (never bound), so tests' monkeypatching of those modules keeps working.
"""

from collections.abc import AsyncGenerator

from app.services import llamacpp_admin, llamacpp_client, llamacpp_pool
from app.services.engine_support_checker import LlamaCppSupportChecker
from app.services.engines.base import EngineCapabilities, InferenceEngine
from app.services.llamacpp_errors import LlamaCppError
from app.services.llamacpp_rerank import LlamaCppRerankClient


class LlamaCppEngine(InferenceEngine):
    name = "llamacpp"
    display_name = "llama.cpp"
    capabilities = EngineCapabilities(
        embeddings=True,
        model_management=True,
        stop_model=True,
        local_process=True,
        host_pool=True,
        support_checking=False,
        tools=True,
        vision=True,
        format_introspection=False,
        rerank=True,
    )
    error_types = (LlamaCppError,)
    support_checker = LlamaCppSupportChecker

    async def list_models(self) -> list[dict]:
        return await llamacpp_client.list_models()

    def chat_stream(self, model: str, messages: list[dict], params: dict) -> AsyncGenerator[str, None]:
        return llamacpp_client.chat_stream(model, messages, params)

    async def chat_once(self, model: str, messages: list[dict], params: dict | None = None) -> str:
        return await llamacpp_client.chat_once(model, messages, params)

    async def check_health(self) -> dict[str, bool]:
        return await llamacpp_pool.check_hosts()

    async def embed(self, text: str, model: str) -> list[float]:
        return await llamacpp_client.embed(text, model)

    async def rerank(self, query: str, documents: list[str], model: str) -> list[float]:
        return await LlamaCppRerankClient().rerank(query, documents, model)

    async def stop_model(self, model: str, request_id: str | None = None) -> None:
        # Unloads the whole model (a dropped connection already ends the request), so the id is unused.
        await llamacpp_client.stop_model(model)

    def pull_model_stream(self, tag: str) -> AsyncGenerator[dict, None]:
        return llamacpp_admin.pull_model_stream(tag)

    async def delete_model(self, tag: str) -> None:
        await llamacpp_admin.delete_model(tag)
