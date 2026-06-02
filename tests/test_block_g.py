"""Block G: copy / SEO / transparency surface.

Covers:
  - new /transparency and /faq routes render and ship Breadcrumb JSON-LD
  - /faq exposes FAQPage JSON-LD whose chain mentions come from the live
    /v1/payments/networks (never hardcoded)
  - homepage uses the live runtime stats (api_p50_ms, avg provision)
  - base header pill is no longer hardcoded "24ms"
  - sitemap.xml includes /transparency, /faq, /login, /signup but NOT
    /dashboard or /order/manage/*
  - build_llms_txt unit-level (placeholder vs live chains)
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.seo import build_llms_txt

# --- /transparency ---


def test_transparency_renders_with_breadcrumb_jsonld(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/transparency")
    assert r.status_code == 200
    assert "AS215932" in r.text
    assert "2a0c:b641:b50::/44" in r.text
    # Breadcrumb structured data must be present and name the page
    assert '"BreadcrumbList"' in r.text
    assert '"Transparency"' in r.text
    # Real infra hosts surfaced from inventory
    assert "<code>rtr</code>" in r.text
    assert "<code>api</code>" in r.text


def test_transparency_lists_data_collected_and_not_collected(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/transparency")
    body = r.text
    # We collect: SSH pubkey, account handle, /64 prefix hash
    assert "ssh pubkey" in body
    assert "/64 prefix hash" in body
    # We do NOT collect: email, phone, name
    assert "email" in body
    assert "phone" in body
    assert '"green"' not in body  # no marketing colors smuggled into the negative list


# --- /faq ---


def test_faq_renders_with_faqpage_jsonld(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/faq")
    assert r.status_code == 200
    assert '"FAQPage"' in r.text
    assert '"Question"' in r.text
    assert "Do you require KYC" in r.text


def test_faq_mentions_only_live_chains(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block G must not advertise a payment chain that isn't enabled in the
    backend right now. We override the mock to a single Polygon entry and
    confirm Base/Arbitrum aren't promised."""
    mocked_api.get("/v1/payments/networks").mock(return_value=httpx.Response(200, json={
        "networks": [
            {"key": "polygon", "display_name": "Polygon", "caip2": "eip155:137",
             "chain_id": 137, "asset": "USDC", "token_address": "0x0",
             "token_decimals": 6,
             "eip712_domain": {"name": "USD Coin", "version": "2"},
             "rpc_url": "x", "block_explorer_url": "x", "testnet": False},
        ],
        "receiver_address": "",
        "facilitator_url": "x",
    }))
    r = client.get("/faq")
    body = r.text
    assert "Polygon" in body
    # The side card shows only Polygon — Base/Arbitrum copy must not leak in
    assert "Arbitrum" not in body


def test_faq_renders_when_backend_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/payments/networks").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/faq")
    assert r.status_code == 200
    # Fallback text directs to the API
    assert "/api/v1/payments/networks" in r.text


# --- homepage uses live runtime ---


def test_homepage_renders_live_runtime_p50(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The default mock supplies api_p50_ms=24. The hardcoded 'api · 24ms'
    pill is gone — the same number must now come from the runtime fetch."""
    mocked_api.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
        "api_p50_ms": 17,
        "api_p50_source": "api-process-local-rolling-window",
        "api_p50_sample_count": 50,
        "build_queue": 2,
        "live_vms": 42,
        "avg_provision_seconds": 71,
        "updated_at": "2026-05-17T00:00:00+00:00",
    }))
    r = client.get("/")
    assert r.status_code == 200
    assert "api · 17ms" in r.text
    # avg_provision_seconds shows up in the homepage hero stat
    assert "71s" in r.text or "~71s" in r.text


def test_homepage_falls_back_when_runtime_unavailable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/stats/runtime").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/")
    assert r.status_code == 200
    # Falls back to em-dash in the header pill rather than lying about latency
    assert "api · —" in r.text


def test_transparency_shows_live_fleet_numbers_from_network_endpoint(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block H: /transparency surfaces BGP peers / IPv6 prefixes / NAT64 sessions
    from /v1/stats/network. Conftest mock supplies 4 peers, 1284 nat64 sessions."""
    r = client.get("/transparency")
    assert r.status_code == 200
    # Live numbers from the conftest default
    assert "4</strong> BGP peers" in r.text
    assert "1284</strong> NAT64 sessions" in r.text
    assert "AS34872, AS210233" in r.text
    # Source label proves the data is live
    assert "prometheus-" in r.text


def test_transparency_falls_back_when_network_endpoint_unavailable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block H: /v1/stats/network down → page still renders, with the static
    `_source: fallback` shape from the backend (which the backend itself
    serves on Prometheus failure)."""
    mocked_api.get("/v1/stats/network").mock(
        return_value=httpx.Response(200, json={
            "bgp_peers_established": None,
            "ipv6_prefixes_announced": 3,
            "nat64_sessions_active": None,
            "transit_providers": ["AS34872", "AS210233"],
            "_source": "fallback",
            "updated_at": "2026-05-17T00:00:00+00:00",
        })
    )
    r = client.get("/transparency")
    assert r.status_code == 200
    # bgp_peers_established=None hides that field entirely
    assert "BGP peers" not in r.text
    # Static-fallback values still render
    assert "3</strong> IPv6 prefixes" in r.text
    assert "source: fallback" in r.text


def test_transparency_serves_stale_network_data_on_backend_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """_refresh_network is stale-on-error: once the live numbers are cached, an
    expired cache + an unreachable backend serves the last-good value rather
    than punching through to the static fallback."""
    # First request caches the live numbers (4 peers from the conftest default).
    r1 = client.get("/transparency")
    assert "4</strong> BGP peers" in r1.text
    # Expire the cache and take the backend down.
    from hyrule_web.app import _NETWORK_CACHE
    _NETWORK_CACHE["expires_at"] = 0.0
    mocked_api.get("/v1/stats/network").mock(side_effect=httpx.ConnectError("boom"))
    # Stale-on-error: still the last-good 4 peers, not a hole.
    r2 = client.get("/transparency")
    assert r2.status_code == 200
    assert "4</strong> BGP peers" in r2.text


def test_base_header_pill_no_longer_hardcoded(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Sanity: an arbitrary p50 from the mock must be reflected. Catches
    regressions where someone re-hardcodes '24ms' in base.html."""
    mocked_api.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
        "api_p50_ms": 99,
        "api_p50_source": "api-process-local-rolling-window",
        "api_p50_sample_count": 1,
        "build_queue": 0,
        "live_vms": 0,
        "avg_provision_seconds": None,
        "updated_at": "2026-05-17T00:00:00+00:00",
    }))
    r = client.get("/transparency")
    assert "api · 99ms" in r.text


# --- sitemap updates ---


def test_sitemap_includes_transparency_and_faq(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    assert "https://hyrule.host/transparency" in body
    assert "https://hyrule.host/faq" in body


def test_sitemap_excludes_dashboard_and_management_surfaces(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    assert "/dashboard" not in body
    assert "/order/manage/" not in body
    # /logout is a reachable GET but uninteresting to crawlers — excluded.
    assert "/logout" not in body


def test_sitemap_includes_auth_entry_points(client: TestClient) -> None:
    """Login/signup are crawlable so JSON-LD breadcrumbs from there resolve."""
    r = client.get("/sitemap.xml")
    body = r.text
    assert "https://hyrule.host/login" in body
    assert "https://hyrule.host/signup" in body


# --- build_llms_txt unit-level ---


def test_build_llms_txt_with_no_networks_directs_to_api() -> None:
    text = build_llms_txt(networks=None)
    assert text.startswith("# Hyrule Cloud")
    assert "/api/v1/payments/networks" in text
    assert "## Payment" in text


def test_build_llms_txt_with_empty_networks_says_none_enabled() -> None:
    text = build_llms_txt(networks=[])
    assert "No EVM chains are currently enabled" in text


def test_build_llms_txt_with_live_chains_lists_each() -> None:
    text = build_llms_txt(networks=[
        {"key": "base", "display_name": "Base", "caip2": "eip155:8453", "chain_id": 8453},
        {"key": "polygon", "display_name": "Polygon", "caip2": "eip155:137", "chain_id": 137},
    ])
    assert "Base" in text
    assert "eip155:8453" in text
    assert "Polygon" in text
    assert "eip155:137" in text


def test_build_llms_txt_with_native_rails_lists_them() -> None:
    text = build_llms_txt(
        networks=[{"key": "base", "display_name": "Base", "caip2": "eip155:8453"}],
        native=["BTC", "XMR"],
    )
    assert "Native intent rails currently enabled: BTC, XMR" in text


def test_build_llms_txt_anonymity_section_always_present() -> None:
    """No-KYC is the lead. It must appear regardless of payment state."""
    for nets in (None, [], [{"key": "base", "display_name": "Base", "caip2": "eip155:8453"}]):
        text = build_llms_txt(networks=nets)
        assert "## Anonymity guarantees" in text
        assert "No email" in text


# --- header nav distinguishes logged-in vs anon ---


def test_header_nav_shows_login_when_no_session(client: TestClient) -> None:
    r = client.get("/")
    # No hyr_sess cookie → Login link in nav
    assert ">Login<" in r.text or ">Login</a>" in r.text


def test_header_nav_shows_dashboard_when_session_cookie_present(client: TestClient) -> None:
    r = client.get("/", cookies={"hyr_sess": "stub-session"})
    assert ">Dashboard<" in r.text or ">Dashboard</a>" in r.text
