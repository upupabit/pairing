"""Matricxon's errors as pAIring sees them, and which error replies are worth another node (cluster failover)."""

import json


class MatricxonError(Exception):
    """Raised when Matricxon is unreachable or errors; like llamacpp_client.LlamaCppError, a separate type (no shared
    base) so one engine's errors can't be caught as the other's. inference_client normalizes both into InferenceError.
    """


class MatricxonHostError(MatricxonError):
    """An error reply another node may not give: out of memory or no GPU (503), a failed load (500), a model this
    node lacks (404). matricxon_pool retries these on the next node; a bad request (400/409) fails everywhere alike.
    """


class MatricxonReply:
    """Turns an error reply into the exception to raise, with Matricxon's own message."""

    @staticmethod
    def error(body: bytes, status_code: int) -> MatricxonError:
        detail = MatricxonReply.detail(body, status_code)
        retryable = status_code >= 500 or status_code == 404
        return MatricxonHostError(detail) if retryable else MatricxonError(detail)

    @staticmethod
    def detail(body: bytes, status_code: int) -> str:
        """Matricxon's `{"error": "..."}` detail (the shape of every typed error in ../matricxon/app/server/errors.py),
        else the raw text (an unhandled exception's plain body), and only then a generic message.
        """
        try:
            detail = json.loads(body).get("error")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        if not detail:
            detail = body.decode("utf-8", errors="replace").strip() or None
        return detail or f"Matricxon returned HTTP {status_code} with no error detail."
