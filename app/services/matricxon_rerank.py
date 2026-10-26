"""Reranking through Matricxon's POST /api/rerank (Knowledge base retrieval, document_retrieval.py). Fails over like
chat and embeddings: a down node, or an error reply another node may not give (matricxon_errors.MatricxonHostError).
"""

import httpx

from app.services import matricxon_http, matricxon_pool
from app.services.matricxon_errors import MatricxonError, MatricxonHostError, MatricxonReply

_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class MatricxonRerankClient:
    async def rerank(self, query: str, documents: list[str], model: str) -> list[float]:
        """Scores in the same order as `documents` (Matricxon returns them best first)."""

        async def _results_from(host: str) -> list[dict]:
            async with matricxon_http.client(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{host}/api/rerank", json={"model": model, "query": query, "documents": documents}
                )
            if resp.is_error:
                raise MatricxonReply.error(resp.content, resp.status_code)
            return resp.json()["results"]

        try:
            results = await matricxon_pool.call_with_failover(_results_from, retry_on=(MatricxonHostError,))
        except (MatricxonError, httpx.HTTPError) as exc:
            raise MatricxonError(f"Rerank request failed: {exc}") from exc
        scores = [0.0] * len(documents)
        for result in results:
            scores[result["index"]] = float(result["relevance_score"])
        return scores
