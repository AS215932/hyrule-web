"""SEO routes — /robots.txt, /sitemap.xml, /llms.txt."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.seo import LLMS_TXT, ROBOTS_TXT


def test_robots_txt_route(client: TestClient) -> None:
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert r.text == ROBOTS_TXT


def test_llms_txt_route_renders_from_live_networks(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """LLMS_TXT is now built from the live /v1/payments/networks response —
    the chain list MUST come from the backend, not a hardcoded constant.
    The default mock in conftest registers Base."""
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert r.text.startswith("# Hyrule Cloud")
    # The mocked default chain must show up in the rendered text.
    assert "Base" in r.text
    assert "eip155:8453" in r.text
    # No-KYC line is part of the preamble.
    assert "No-KYC" in r.text or "no-KYC" in r.text


def test_llms_txt_route_falls_back_when_backend_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """When /v1/payments/networks fails, llms.txt MUST render the placeholder
    rather than lying about chains we may have disabled."""
    mocked_api.get("/v1/payments/networks").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/llms.txt")
    assert r.status_code == 200
    # The fallback text directs to the API for the live list.
    assert "/api/v1/payments/networks" in r.text
    # And it must NOT advertise the paid diagnostics suite — we cannot
    # confirm those routes are live when discovery itself failed.
    assert "Paid network diagnostics" not in r.text
    assert "/v1/dns/lookup" not in r.text


def test_llms_txt_constant_is_the_fallback_variant() -> None:
    """The exported LLMS_TXT constant is the no-networks-known fallback,
    so any caller that imports it still gets a sensible string."""
    assert LLMS_TXT.startswith("# Hyrule Cloud")
    assert "/api/v1/payments/networks" in LLMS_TXT


def test_llms_txt_advertises_paid_network_diagnostics(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The operation section is generated only from enabled OpenAPI."""
    r = client.get("/llms.txt")
    assert r.status_code == 200
    text = r.text
    assert "/v1/dns/lookup" in text
    assert "/v1/bgp/lookup" in text
    assert "/v1/web/tls/deep" in text
    assert "/v1/network/request" in text
    # Operations absent from the enabled document must not be promised.
    assert "/v1/mx/check" not in text
    assert "/v1/mail" not in text
    assert "/v1/speedtest" not in text


def test_sitemap_xml_route_is_valid_xml(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]
    root = ET.fromstring(r.text)
    assert root.tag.endswith("urlset")


def test_sitemap_xml_excludes_api_partials_and_dynamic_routes(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    assert "/api/" not in body
    assert "/partials/" not in body
    assert "/order/status/" not in body  # dynamic per-user
    assert "/order/review" not in body  # POST-only


def test_sitemap_xml_includes_known_public_paths(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    for path in (
        "https://hyrule.host/",
        "https://hyrule.host/services",
        "https://hyrule.host/order",
        "https://hyrule.host/about",
        "https://hyrule.host/llms.txt",
        "https://hyrule.host/terms",
        "https://hyrule.host/privacy",
        "https://hyrule.host/abuse",
        "https://hyrule.host/legal",
    ):
        assert path in body
    assert "https://hyrule.host/transparency" not in body


def test_llms_txt_diagnostics_need_an_enabled_chain_and_live_discovery() -> None:
    """No payable x402 chain (empty list) or a stale cached catalog must both
    suppress the paid-diagnostics section."""
    from hyrule_web.seo import build_llms_txt

    base = {
        "key": "base",
        "display_name": "Base",
        "caip2": "eip155:8453",
        "chain_id": 8453,
        "family": "evm",
    }

    tool = {
        "method": "POST",
        "path": "/v1/dns/lookup",
        "description": "DNS",
        "price_display": "$0.001",
        "executable": True,
    }
    live = build_llms_txt([base], diagnostics_live=True, tools=[tool])
    assert "Enabled x402 operations" in live

    no_chains = build_llms_txt([], diagnostics_live=True, tools=[tool])
    assert "Enabled x402 operations" not in no_chains

    stale = build_llms_txt([base], diagnostics_live=False, tools=[tool])
    assert "Enabled x402 operations" not in stale

    # The golden path needs EIP-3009 signing: an SVM-only catalog is not a
    # payable x402 surface for these endpoints.
    svm_only = build_llms_txt(
        [{"key": "solana", "display_name": "Solana", "family": "svm"}],
        diagnostics_live=True,
        tools=[tool],
    )
    assert "Enabled x402 operations" not in svm_only
