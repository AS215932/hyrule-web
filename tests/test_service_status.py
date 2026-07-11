"""Server-rendered platform status control and /status page."""

from __future__ import annotations

import time

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.app import _SERVICE_STATUS_CACHE, _SERVICE_STATUS_TTL_SECONDS


def _status_payload(
    state: str = "operational",
    *,
    component_state: str = "operational",
    component: str = "compute",
    stale: bool = False,
) -> dict:
    components = [
        {"id": "api_checkout", "name": "API & checkout", "status": "operational",
         "message": "Purchasing and management API"},
        {"id": "compute", "name": "Compute", "status": "operational",
         "message": "VM provisioning and reachability"},
        {"id": "intelligence", "name": "Network intelligence", "status": "operational",
         "message": "Network diagnostics endpoints"},
        {"id": "domains_dns", "name": "Domains & DNS", "status": "operational",
         "message": "Registration and authoritative DNS"},
        {"id": "network_proxy", "name": "Network proxy", "status": "operational",
         "message": "Direct, Tor, I2P, and Yggdrasil egress"},
    ]
    selected = next(row for row in components if row["id"] == component)
    selected["status"] = component_state
    selected["message"] = "New VM provisioning is delayed."
    incidents = []
    if component_state in {"degraded", "outage"}:
        incidents.append({
            "id": "inc_public123",
            "title": "VM provisioning degraded",
            "message": "New VM provisioning is delayed.",
            "status": component_state,
            "component_ids": [component],
            "started_at": "2026-07-11T12:00:00+00:00",
        })
    return {
        "status": state,
        "checked_at": "2026-07-11T12:01:00+00:00",
        "stale": stale,
        "components": components,
        "incidents": incidents,
    }


def test_operational_header_and_status_page(client: TestClient) -> None:
    home = client.get("/")
    assert "Operational" in home.text
    assert 'popovertarget="service-status-popover"' in home.text
    assert 'href="/status"' in home.text

    page = client.get("/status")
    assert page.status_code == 200
    assert "No active incidents" in page.text
    assert "API &amp; checkout" in page.text
    assert "Network intelligence" in page.text


def test_degraded_header_names_single_affected_service(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/status").mock(
        return_value=httpx.Response(
            200,
            json=_status_payload("degraded", component_state="degraded"),
        )
    )
    _SERVICE_STATUS_CACHE["expires_at"] = 0.0

    response = client.get("/")

    assert "Degraded · Compute" in response.text
    assert "New VM provisioning is delayed." in response.text


def test_outage_incident_explains_customer_impact(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/status").mock(
        return_value=httpx.Response(
            200,
            json=_status_payload("outage", component_state="outage"),
        )
    )
    _SERVICE_STATUS_CACHE["expires_at"] = 0.0

    response = client.get("/status")

    assert "Major outage" in response.text
    assert "VM provisioning degraded" in response.text
    assert "New VM provisioning is delayed." in response.text


def test_stale_or_unreachable_feed_never_renders_green(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/status").mock(side_effect=httpx.ConnectError("down"))
    _SERVICE_STATUS_CACHE.update(value=None, expires_at=0.0, successful_at=0.0)

    response = client.get("/")

    assert "Status feed delayed" in response.text
    assert "The live status feed is unavailable." in response.text
    assert "status-operational" not in response.text

    status_page = client.get("/status")
    assert "No incident details are available" in status_page.text
    assert "status-operational" not in status_page.text


def test_status_cache_short_circuits_repeated_page_requests(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.get("/v1/status").mock(
        return_value=httpx.Response(200, json=_status_payload())
    )
    _SERVICE_STATUS_CACHE.update(value=None, expires_at=0.0, successful_at=0.0)

    client.get("/")
    client.get("/services")
    client.get("/faq")

    assert route.call_count == 1
    assert _SERVICE_STATUS_CACHE["expires_at"] > time.time()
    assert _SERVICE_STATUS_TTL_SECONDS == 15


def test_legacy_broken_status_url_redirects(client: TestClient) -> None:
    response = client.get("/order/status", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/status"
