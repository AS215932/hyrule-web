"""Top-level page rendering and the os_templates fallback branch in
page_services / page_order.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient


def _assert_html_with_canonical(r: httpx.Response) -> None:
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'rel="canonical"' in r.text


def test_index(client: TestClient) -> None:
    r = client.get("/")
    _assert_html_with_canonical(r)


def test_dashboard(client: TestClient) -> None:
    r = client.get("/dashboard")
    _assert_html_with_canonical(r)


def test_services_uses_api_data_when_present(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/os/list").mock(return_value=httpx.Response(
        200,
        json={"templates": [
            {"name": "ubuntu-24.04", "description": "Ubuntu 24.04", "default": True},
        ]},
    ))
    r = client.get("/services")
    _assert_html_with_canonical(r)
    assert "Ubuntu 24.04" in r.text


def test_services_falls_back_when_api_returns_no_templates_key(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    # 200 but missing 'templates' — code path: os_data.get("templates", DEFAULT_OS_TEMPLATES)
    mocked_api.get("/v1/os/list").mock(return_value=httpx.Response(200, json={}))
    r = client.get("/services")
    _assert_html_with_canonical(r)
    assert "Debian 13" in r.text


def test_services_falls_back_when_api_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/os/list").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/services")
    _assert_html_with_canonical(r)
    assert "Debian 13" in r.text  # fell back to DEFAULT_OS_TEMPLATES


def test_order_uses_api_data_when_present(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/os/list").mock(return_value=httpx.Response(
        200,
        json={"templates": [
            {"name": "alpine-3.21", "description": "Alpine 3.21", "default": True},
        ]},
    ))
    r = client.get("/order")
    _assert_html_with_canonical(r)


def test_order_falls_back_when_api_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/os/list").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/order")
    _assert_html_with_canonical(r)
