"""Reranking through llama-server's POST /v1/rerank (Knowledge base retrieval, document_retrieval.py). The model
runs with reranking on (llamacpp_preset marks rank-pooling models).
"""

import httpx

from app.services import llamacpp_admin, llamacpp_pool
from app.services.llamacpp_errors import LlamaCppError
from app.services.llamacpp_models import LlamaCppModelName

_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class LlamaCppRerankClient:
    async def rerank(self, query: str, documents: list[str], model: str) -> list[float]:
        """Scores in the same order as `documents` (llama-server may return them in another order). Retried once
        after rebuilding the router's model list if it doesn't know the model.
        """
        try:
            return await self._rerank(query, documents, model)
        except LlamaCppError as exc:
            if not await llamacpp_admin.reload_if_unknown(str(exc)):
                raise
            return await self._rerank(query, documents, model)

    async def _rerank(self, query: str, documents: list[str], model: str) -> list[float]:
        host = llamacpp_pool.pick_host()
        name = LlamaCppModelName.to_router(model) if llamacpp_pool.is_local() else model
        async with llamacpp_pool.track_request(host):
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                try:
                    resp = await client.post(
                        f"{host}/v1/rerank", json={"model": name, "query": query, "documents": documents}
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    if not isinstance(exc, httpx.HTTPStatusError):
                        llamacpp_pool.mark_failure(host)
                    detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                    raise LlamaCppError(f"Rerank request failed: {detail}") from exc
        llamacpp_pool.mark_recovered(host)
        scores = [0.0] * len(documents)
        for result in resp.json()["results"]:
            scores[result["index"]] = float(result["relevance_score"])
        return scores
