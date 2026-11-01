"""The newer sampling options (min_p, presence and frequency penalties) for the local engines. Only those turned on
are sent, so a request with them all off is exactly what it was before (and llama.cpp keeps its own min_p default)."""

EXTRA_KEYS = ("min_p", "presence_penalty", "frequency_penalty")


class SamplingExtras:
    @staticmethod
    def of(params: dict) -> dict[str, float]:
        return {key: float(params[key]) for key in EXTRA_KEYS if params.get(key)}
