"""/api/{path:path} proxy — methods, v1/ strip, header allowlist, body fwd, errors.

The hop-by-hop drop test guards against someone widening the request-header
allowlist in app.py later without realising they'd start leaking client-side
headers (Host, Connection, etc.) into backend calls.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient


def test_proxy_get_no_v1_prefix(client: TestClient, mocked_api: respx.MockRouter) -> None:
    route = mocked_api.get("/v1/ping").mock(return_value=httpx.Response(200, json={"ok": True}))
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert route.called


def test_proxy_get_with_v1_prefix_is_stripped(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    # /api/v1/foo should strip "v1/" then re-prepend "/v1/" → still /v1/foo backend.
    route = mocked_api.get("/v1/foo").mock(return_value=httpx.Response(200, json={"ok": True}))
    r = client.get("/api/v1/foo")
    assert r.status_code == 200
    assert route.called


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_proxy_forwards_every_supported_method(
    client: TestClient, mocked_api: respx.MockRouter, method: str
) -> None:
    route = mocked_api.route(method=method, path="/v1/things").mock(
        return_value=httpx.Response(204)
    )
    r = client.request(method, "/api/things", content=b"x" if method != "GET" else None)
    assert r.status_code == 204
    assert route.called


def test_proxy_forwards_allowlisted_header(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/pay").mock(return_value=httpx.Response(200))
    r = client.post(
        "/api/pay",
        headers={"X-Payment": "abc123", "Content-Type": "application/json"},
        json={},
    )
    assert r.status_code == 200
    seen = route.calls.last.request.headers
    assert seen["x-payment"] == "abc123"
    assert seen["content-type"] == "application/json"


def test_proxy_drops_hop_by_hop_and_unknown_headers(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/pay").mock(return_value=httpx.Response(200))
    r = client.post(
        "/api/pay",
        headers={
            "X-Custom-Random": "leak-me",  # not in allowlist
        },
        json={},
    )
    assert r.status_code == 200
    seen = route.calls.last.request.headers
    assert "x-custom-random" not in seen


def test_proxy_forwards_authorization_header(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: Bearer auth must be forwarded so management tokens
    (hyr_vm_...) reach the backend. Block D will add hyr_sk_ account keys
    via the same path — keep the test now so the allowlist doesn't quietly
    drop them later."""
    route = mocked_api.delete("/v1/vm/vm-abc").mock(return_value=httpx.Response(200))
    r = client.delete(
        "/api/vm/vm-abc",
        headers={"Authorization": "Bearer hyr_vm_test123"},
    )
    assert r.status_code == 200
    seen = route.calls.last.request.headers
    assert seen.get("authorization") == "Bearer hyr_vm_test123"


def test_proxy_forwards_session_cookie(client: TestClient, mocked_api: respx.MockRouter) -> None:
    """Block A1: the browser session cookie must reach the backend so
    /me/* calls (and any future account-scoped endpoint) can resolve the
    current account. Without this, the dashboard would always 401."""
    route = mocked_api.get("/v1/me").mock(return_value=httpx.Response(200, json={}))
    r = client.get("/api/me", headers={"Cookie": "hyr_sess=abc123"})
    assert r.status_code == 200
    seen = route.calls.last.request.headers
    assert "hyr_sess=abc123" in seen.get("cookie", "")


def test_proxy_preserves_set_cookie_on_response(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: backend Set-Cookie headers (e.g. session issued at /login)
    must round-trip to the browser as raw Set-Cookie headers, not be
    collapsed by Starlette's headers dict."""
    mocked_api.post("/v1/auth/login").mock(
        return_value=httpx.Response(
            200,
            headers={"set-cookie": "hyr_sess=secret; HttpOnly; Path=/; SameSite=Lax"},
            json={},
        )
    )
    r = client.post("/api/auth/login", json={"account_id": "x", "password": "y"})
    assert r.status_code == 200
    # TestClient exposes Set-Cookie via the `cookies` jar — verify the cookie
    # actually became a browser cookie, which is the property that matters.
    assert r.cookies.get("hyr_sess") == "secret"


def test_proxy_forwards_request_body(client: TestClient, mocked_api: respx.MockRouter) -> None:
    route = mocked_api.post("/v1/echo").mock(return_value=httpx.Response(200))
    r = client.post(
        "/api/echo", content=b'{"hello":"world"}', headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 200
    assert route.calls.last.request.content == b'{"hello":"world"}'


def test_proxy_handles_empty_body(client: TestClient, mocked_api: respx.MockRouter) -> None:
    route = mocked_api.get("/v1/empty").mock(return_value=httpx.Response(200))
    r = client.get("/api/empty")
    assert r.status_code == 200
    # GET-with-no-body should send None content (exercises the `body if body else None` branch).
    assert route.calls.last.request.content == b""


def test_proxy_returns_502_when_backend_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/down").mock(side_effect=httpx.ConnectError("backend down"))
    r = client.get("/api/down")
    assert r.status_code == 502
    assert "API unreachable" in r.text


def test_proxy_preserves_backend_status(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/teapot").mock(return_value=httpx.Response(418, json={"err": "teapot"}))
    r = client.get("/api/teapot")
    assert r.status_code == 418
    assert "teapot" in r.text


def test_proxy_preserves_query_payment_and_binary_headers(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.get("/v1/bgp/snapshot?format=jsonl").mock(
        return_value=httpx.Response(
            200,
            content=b"gzip-data",
            headers={
                "content-type": "application/gzip",
                "content-disposition": 'attachment; filename="snapshot.jsonl.gz"',
                "payment-response": "receipt",
            },
        )
    )
    response = client.get(
        "/api/bgp/snapshot?format=jsonl",
        headers={"Payment-Signature": "signed-x402"},
    )
    assert response.status_code == 200
    assert response.content == b"gzip-data"
    assert response.headers["content-type"] == "application/gzip"
    assert "snapshot.jsonl.gz" in response.headers["content-disposition"]
    assert response.headers["payment-response"] == "receipt"
    assert route.calls.last.request.headers["payment-signature"] == "signed-x402"
    assert route.calls.last.request.url.query == b"format=jsonl"
