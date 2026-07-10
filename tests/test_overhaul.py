"""RFC-editorial overhaul — four-pillar catalog, /agents, live tier specs.

Covers the three behaviours the overhaul introduced:
- tier grids render the LIVE /v1/products/vms catalog (the hardcoded config
  mirror once drifted: xs shipped 1 GB while the site said 512 MB);
- /services + /agents render per-endpoint prices from the published x402
  manifest, with the curated config fallback when the fetch fails;
- the new /agents page documents the 402 golden path + the async VM contract.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.config import VM_TIERS

_OS_LIST = {
    "templates": [
        {"name": "debian-13", "description": "Debian 13 (Trixie)", "default": True,
         "family": "debian"},
    ]
}


def _mock_os_list(mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/os/list").mock(return_value=httpx.Response(200, json=_OS_LIST))


def test_index_advertises_all_four_pillars(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    # The four service groups, each linking into /services.
    for anchor in ("#compute", "#intel", "#domains", "#proxy"):
        assert f"/services{anchor}" in body
    # Entry prices come from the mocked manifest (conftest).
    assert "$0.05/day" in body  # compute min
    assert "$0.001/req" in body  # intel min
    assert "$6.00" in body  # domains min
    # BCP 14 privacy stance is part of the brand copy.
    assert "MUST NOT" in body


def test_tier_grid_uses_live_product_catalog(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """xs is 1 GB in the live catalog — the 512 MB drift must never return."""
    _mock_os_list(mocked_api)
    r = client.get("/services")
    assert r.status_code == 200
    assert "512 MB" not in r.text
    assert "1 GB" in r.text


def test_tier_grid_falls_back_to_config_when_products_unavailable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    _mock_os_list(mocked_api)
    mocked_api.get("/v1/products/vms").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/services")
    assert r.status_code == 200
    # Fallback renders config.VM_TIERS — whose xs is ALSO 1 GB now.
    assert VM_TIERS["xs"]["ram_mb"] == 1024
    assert "512 MB" not in r.text


def test_services_renders_intel_and_proxy_price_tables(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    _mock_os_list(mocked_api)
    r = client.get("/services")
    assert r.status_code == 200
    body = r.text
    # Intel rows from the mocked manifest.
    assert "/v1/dns/lookup" in body
    assert "$0.001" in body
    assert "/v1/web/tls/deep" in body
    # Proxy routes from the mocked /v1/pricing.
    for route in ("direct", "tor", "i2p", "yggdrasil"):
        assert route in body
    assert "$0.05/request" in body
    # The proxy pin predating the overhaul stays put.
    assert "Paid direct and Tor HTTP requests" in body


def test_services_price_tables_fall_back_to_curated_catalog(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    _mock_os_list(mocked_api)
    mocked_api.get("/.well-known/x402.json").mock(side_effect=httpx.ConnectError("boom"))
    mocked_api.get("/v1/pricing").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/services")
    assert r.status_code == 200
    body = r.text
    # The curated config mirror still lists the flagship endpoints + routes.
    assert "/v1/dns/lookup" in body
    assert "/v1/bgp/lookup" in body
    assert "yggdrasil" in body


def test_agents_page_documents_the_x402_contract(client: TestClient) -> None:
    r = client.get("/agents")
    assert r.status_code == 200
    assert 'rel="canonical"' in r.text
    body = r.text
    # Discovery surfaces.
    assert "/.well-known/x402.json" in body
    assert "/llms.txt" in body
    assert "hyrule-network-intel" in body  # ClawHub skill
    assert "hyrule-mcp" in body  # MCP config
    # The golden path + async VM contract (public status poll, no token).
    assert "X-PAYMENT" in body
    assert "402" in body
    assert "/v1/vm/{id}/status" in body
    assert "management_url" in body
    # Price schedule rows from the mocked manifest.
    assert "/v1/vm/create" in body
    assert "$6.00" in body
    # Live payment rails (mocked catalog registers Base).
    assert "Base" in body
    assert "eip155:8453" in body


def test_agents_in_nav_and_sitemap(client: TestClient) -> None:
    r = client.get("/")
    assert 'href="/agents"' in r.text
    sm = client.get("/sitemap.xml")
    assert "https://hyrule.host/agents" in sm.text


def test_llms_txt_links_the_agents_page(client: TestClient) -> None:
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert "https://hyrule.host/agents" in r.text


def test_implausible_provision_average_is_not_advertised(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Observed in prod: the rolling average returned 4720.3s while real
    provisions finish in seconds. Outside a plausible window the pages must
    fall back to the honest ~60s copy instead of advertising broken telemetry."""
    mocked_api.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
        "api_p50_ms": 24,
        "api_p50_source": "api-process-local-rolling-window",
        "api_p50_sample_count": 100,
        "build_queue": 0,
        "live_vms": 5,
        "avg_provision_seconds": 4720.3,
        "updated_at": "2026-07-10T00:00:00+00:00",
    }))
    r = client.get("/")
    assert r.status_code == 200
    assert "4720" not in r.text
    # The hero stat falls back to its markup-split "~60s" (`<em>~</em>60s`).
    assert "<em>~</em>60s" in r.text
