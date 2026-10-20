"""llama.cpp's error type, in its own module so the client, admin and engine can share it without import cycles."""


class LlamaCppError(Exception):
    """llama-server is unreachable or reported an error; a separate type from other engines' errors
    (inference_client normalizes them all into InferenceError).
    """
