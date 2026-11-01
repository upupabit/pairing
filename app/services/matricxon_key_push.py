"""Sends the API key to Matricxon nodes (PUT /api/cluster/api-key, applied at once, no restart). All or nothing, like
the admin secret (cluster_secret.py): every node must answer first, and a node that refuses puts the others back."""

import httpx

from app.services import matricxon_http
from app.services.cluster_errors import NodeNotAllowedError

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class MatricxonKeyPush:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def push(self, hosts: list[str], new: str, old: str) -> None:
        """Every host ends up with `new` ("" = no key), or, on any failure, all keep `old`."""
        done: list[str] = []
        async with matricxon_http.client(timeout=_TIMEOUT, transport=self._transport) as client:
            silent = [h for h in hosts if not await self._answers(client, h)]
            if silent:
                raise NodeNotAllowedError(
                    "Every Matricxon must answer to change the key; not answering: " + ", ".join(silent)
                )
            for host in hosts:
                problem = await self._put(client, host, new, old)
                if problem:
                    for changed in done:  # they hold the new key now, so that is what proves us
                        await self._put(client, changed, old, new)
                    raise NodeNotAllowedError(f"{host} did not accept the key ({problem}); nothing changed.")
                done.append(host)

    @staticmethod
    async def _answers(client: httpx.AsyncClient, host: str) -> bool:
        try:
            return (await client.get(host + "/api/version")).status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    async def _put(client: httpx.AsyncClient, host: str, key: str, current: str) -> str | None:
        headers = {"Authorization": f"Bearer {current}"} if current else {}
        try:
            resp = await client.put(host + "/api/cluster/api-key", json={"key": key}, headers=headers)
        except httpx.HTTPError as exc:
            return str(exc) or type(exc).__name__
        if resp.status_code == 404:
            return "update its Matricxon"
        if resp.status_code in (401, 403):
            return "it refused this pAIring: check the admin secret"
        return None if resp.is_success else f"HTTP {resp.status_code}"
