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


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
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
            "X-Custom-Random": "leak-me",       # not in allowlist
            "Authorization": "Bearer secret",   # not in allowlist
        },
        json={},
    )
    assert r.status_code == 200
    seen = route.calls.last.request.headers
    assert "x-custom-random" not in seen
    assert "authorization" not in seen


def test_proxy_forwards_request_body(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/echo").mock(return_value=httpx.Response(200))
    r = client.post("/api/echo", content=b'{"hello":"world"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert route.calls.last.request.content == b'{"hello":"world"}'


def test_proxy_handles_empty_body(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
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


def test_proxy_preserves_backend_status(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/teapot").mock(return_value=httpx.Response(418, json={"err": "teapot"}))
    r = client.get("/api/teapot")
    assert r.status_code == 418
    assert "teapot" in r.text
