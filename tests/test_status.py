"""/order/status/{vm_id} and the HTMX /order/status/{vm_id}/partial — both
must render whether the backend returns a VM, an error, or nothing."""

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
    mocked_api.get("/v1/vm/vm-abc").mock(return_value=httpx.Response(200, json=_VM_READY))
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200


def test_status_page_with_missing_vm_renders_anyway(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-missing").mock(return_value=httpx.Response(404))
    r = client.get("/order/status/vm-missing")
    assert r.status_code == 200  # template handles vm=None


def test_status_page_with_backend_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-err").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/order/status/vm-err")
    assert r.status_code == 200


def test_status_partial_with_ready_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc").mock(return_value=httpx.Response(200, json=_VM_READY))
    r = client.get("/order/status/vm-abc/partial")
    assert r.status_code == 200


def test_status_partial_with_missing_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-x").mock(return_value=httpx.Response(404))
    r = client.get("/order/status/vm-x/partial")
    assert r.status_code == 200
