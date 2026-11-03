"""A Matricxon node's version for its panel on the Nodes map (cluster_map.py `node`): read only when the panel
opens, not on every map refresh. "2.1 (f854f64)" from its GET /api/version, the commit when it is a git checkout."""

import httpx

from app.services import matricxon_http

_TIMEOUT = httpx.Timeout(3.0, connect=1.5)


class NodeVersionReader:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def read(self, host: str) -> str | None:
        """None when the node doesn't answer (its panel shows the error instead)."""
        try:
            async with matricxon_http.client(timeout=_TIMEOUT, transport=self._transport) as client:
                resp = await client.get(f"{host.rstrip('/')}/api/version")
            body = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return None
        version = body.get("version")
        if not version:
            return None
        return f"{version} ({body['commit']})" if body.get("commit") else str(version)
