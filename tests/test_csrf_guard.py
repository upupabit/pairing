"""Tests for app/services/csrf_guard.py: state-changing requests with the login cookie must come from this server's
own pages (Origin, else Referer), and instance_proxy_http forwards the browser's host for that check."""

import httpx
import pytest

from app.services.csrf_guard import CsrfOriginMiddleware
from app.services.instance_proxy_http import filter_request_headers

COOKIE = {"cookie": "pairing_session=abc"}
HOST = "chat.local:8000"


async def _ok_app(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _status(
    method: str, headers: dict[str, str], client_ip: str = "10.0.0.5", trusted: list[str] | None = None
) -> int:
    app = CsrfOriginMiddleware(_ok_app, cookie_name="pairing_session", trusted_origins=trusted)
    transport = httpx.ASGITransport(app=app, client=(client_ip, 1234))
    async with httpx.AsyncClient(transport=transport, base_url=f"http://{HOST}") as client:
        return (await client.request(method, "/api/x", headers=headers)).status_code


@pytest.mark.asyncio
async def test_same_origin_posts_pass_and_foreign_ones_are_blocked() -> None:
    assert await _status("POST", COOKIE | {"origin": f"http://{HOST}"}) == 200
    assert await _status("DELETE", COOKIE | {"origin": "http://chat.local:8600"}) == 403
    assert await _status("PATCH", COOKIE | {"origin": "https://evil.example"}) == 403
    assert await _status("POST", COOKIE | {"origin": "null"}) == 403


@pytest.mark.asyncio
async def test_referer_is_used_without_origin() -> None:
    assert await _status("PUT", COOKIE | {"referer": f"http://{HOST}/settings"}) == 200
    assert await _status("PUT", COOKIE | {"referer": "http://chat.local:8600/page"}) == 403


@pytest.mark.asyncio
async def test_reads_requests_without_the_cookie_and_non_browsers_pass() -> None:
    foreign = {"origin": "https://evil.example"}
    assert await _status("GET", COOKIE | foreign) == 200
    assert await _status("POST", foreign) == 200
    assert await _status("POST", COOKIE) == 200
    assert await _status("POST", COOKIE | {"origin": "not a url"}) == 403


@pytest.mark.asyncio
async def test_forwarded_host_counts_only_from_loopback() -> None:
    proxied = COOKIE | {"origin": "https://chat.example.com", "x-forwarded-host": "chat.example.com"}
    assert await _status("POST", proxied, client_ip="127.0.0.1") == 200
    assert await _status("POST", proxied, client_ip="10.0.0.5") == 403


@pytest.mark.asyncio
async def test_trusted_origins_and_default_ports() -> None:
    other = COOKIE | {"origin": "https://chat.example.com"}
    assert await _status("POST", other, trusted=["https://chat.example.com"]) == 200
    assert await _status("POST", other, trusted=["chat.example.com"]) == 200
    assert await _status("POST", other, trusted=["https://other.example.com"]) == 403
    assert CsrfOriginMiddleware._host_of("https://Chat.Local:443") == CsrfOriginMiddleware._host_of("//chat.local")


def test_the_balancer_forwards_the_browser_host_and_drops_a_client_supplied_one() -> None:
    raw = [
        (b"host", b"chat.local:8000"),
        (b"x-forwarded-host", b"evil.example"),
        (b"origin", b"http://chat.local:8000"),
    ]

    headers = filter_request_headers(raw, "10.0.0.5")

    assert ("X-Forwarded-Host", "chat.local:8000") in headers
    assert ("x-forwarded-host", "evil.example") not in headers
    assert ("origin", "http://chat.local:8000") in headers
