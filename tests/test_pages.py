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


def test_dashboard_redirects_to_login_when_not_authed(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: /dashboard hits backend /v1/me. Without a session the backend
    returns 401 and the page handler redirects to /login."""
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(401))
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_dashboard_redirects_when_backend_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: backend unreachable on /v1/me is treated the same as
    not-authed — bounce to /login. A logged-in user retrying after a brief
    outage will land back on /dashboard once the backend recovers."""
    mocked_api.get("/v1/me").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_dashboard_renders_with_vms_when_authed(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: when /v1/me returns 200, the dashboard renders the VM table
    sourced from /v1/me/vms."""
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(200, json={
        "account_id": "ACCT_ABC",
        "vm_count": 2,
        "created_at": "2026-05-01T10:00:00+00:00",
    }))
    mocked_api.get("/v1/me/vms").mock(return_value=httpx.Response(200, json={
        "vms": [
            {"vm_id": "vm-aaa", "status": "ready", "os": "debian-13",
             "size": "sm", "ipv6": "2a0c:b641::1", "expires_at": "2026-06-01T00:00:00+00:00"},
            {"vm_id": "vm-bbb", "status": "ready", "os": "alpine-3.21",
             "size": "md", "ipv6": "2a0c:b641::2", "expires_at": None},
        ],
    }))
    r = client.get("/dashboard")
    _assert_html_with_canonical(r)
    assert "ACCT_ABC" in r.text
    assert "vm-aaa" in r.text
    assert "vm-bbb" in r.text


def test_dashboard_renders_error_banner_when_me_5xxs(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: a 5xx on /v1/me (not 401) renders the dashboard shell with
    an error banner instead of redirecting — the user can still log out."""
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(500))
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Could not load account info" in r.text


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
    assert "Paid direct and Tor HTTP requests" in r.text
    assert "support-assisted beta" not in r.text


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
    assert 'name="domain_mode" value="custom"' in r.text
    assert 'name="domain"' in r.text
    assert 'inputmode="text"' in r.text
    assert 'name="domain" placeholder="example.com" inputmode="text" autocomplete="off" disabled' in r.text
    assert "support-assisted beta" not in r.text


def test_order_falls_back_when_api_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/os/list").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/order")
    _assert_html_with_canonical(r)


def test_legal_pages_render(client: TestClient) -> None:
    for path, needle in (
        ("/terms", "Customer Responsibilities"),
        ("/privacy", "No-KYC Model"),
        ("/abuse", "Report Channels"),
        ("/legal", "Crypto Payment Posture"),
    ):
        r = client.get(path)
        _assert_html_with_canonical(r)
        assert needle in r.text
        assert "abuse@as215932.net" in r.text
