"""/order/status/{vm_id} and the HTMX /order/status/{vm_id}/partial — both
must render whether the backend returns a VM, an error, or nothing.

Block A0 (2026-05-18): the upstream API now serves the sanitized status
shape at `/v1/vm/{id}/status` (the legacy `/v1/vm/{id}` is management-
gated). The fixtures + URL patterns below were updated accordingly. Plus
a new test covers the post-order management-URL banner.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

_VM_READY = {
    "id": "vm-abc",
    "order_id": "ord-1",
    "size": "md",
    "status": "ready",
    "hostname": "test",
    "fqdn": "test.deploy.hyrule.host",
}


def test_status_page_with_ready_vm(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(return_value=httpx.Response(200, json=_VM_READY))
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200


def test_status_page_with_missing_vm_renders_anyway(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-missing/status").mock(return_value=httpx.Response(404))
    r = client.get("/order/status/vm-missing")
    assert r.status_code == 200  # template handles vm=None


def test_status_page_with_backend_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-err/status").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/order/status/vm-err")
    assert r.status_code == 200


def test_status_partial_with_ready_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(return_value=httpx.Response(200, json=_VM_READY))
    r = client.get("/order/status/vm-abc/partial")
    assert r.status_code == 200


def test_status_partial_with_missing_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-x/status").mock(return_value=httpx.Response(404))
    r = client.get("/order/status/vm-x/partial")
    assert r.status_code == 200


# --- Block A0 management-URL banner ---


def test_status_page_renders_management_banner_when_token_query_present(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: when the post-order redirect carries ?token=hyr_vm_...,
    the status page renders the save-once management URL banner with
    the exact canonical URL — `cloud.` subdomain prefix, `www.` stripped
    from the request host, and the token URL-encoded."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_READY),
    )
    r = client.get(
        "/order/status/vm-abc?token=hyr_vm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        headers={"host": "www.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "save this once" in body.lower()
    # The banner offers a copy button + download link.
    assert "download" in body.lower()
    # Exact URL shape: scheme://cloud.<stripped-host>/v1/vm/<id>?token=<urlencoded>
    expected = (
        "http://cloud.example.com/v1/vm/vm-abc"
        "?token=hyr_vm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert expected in body


def test_status_page_renders_management_banner_even_when_api_404s(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: a transient API outage (or eventual-consistency gap)
    between order success and the redirect must not eat the one-time
    management URL. The banner must render even when /status returns
    404 — it's the user's only chance to capture the token."""
    mocked_api.get("/v1/vm/vm-late/status").mock(
        return_value=httpx.Response(404),
    )
    r = client.get(
        "/order/status/vm-late?token=hyr_vm_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert r.status_code == 200
    body = r.text
    assert "save this once" in body.lower()
    assert "hyr_vm_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in body


def test_status_page_no_banner_without_token(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: the banner only renders when ?token= is present. A
    regular status check (e.g. polled later, or shared link) must NOT
    leak any management hint."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_READY),
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "save this once" not in r.text.lower()


def test_status_page_ignores_malformed_token_query(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: ?token= must start with `hyr_vm_` to be surfaced. Random
    junk in the query string does not cause a banner to render with that
    junk embedded."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_READY),
    )
    r = client.get("/order/status/vm-abc?token=not-a-real-token")
    assert r.status_code == 200
    assert "save this once" not in r.text.lower()
    assert "not-a-real-token" not in r.text
