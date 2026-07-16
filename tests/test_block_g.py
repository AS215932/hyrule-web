"""Block G: copy / SEO / policy surface.

Covers:
  - /about and /faq routes render and ship Breadcrumb JSON-LD
  - /faq exposes FAQPage JSON-LD whose chain mentions come from the live
    /v1/payments/networks (never hardcoded)
  - homepage uses the live runtime stats (api_p50_ms, avg provision)
  - service status in the header is independent of runtime latency
  - sitemap.xml includes /about, /faq, /login, /signup but NOT
    /dashboard or /order/manage/*
  - build_llms_txt unit-level (placeholder vs live chains)
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.seo import build_llms_txt

# --- /about ---


def test_about_renders_mission_policy_and_breadcrumb_jsonld(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/about")
    assert r.status_code == 200
    assert "The Agentic ISP" in r.text
    assert "Operating principles" in r.text
    assert "Abuse handling" in r.text
    assert '"BreadcrumbList"' in r.text
    assert '"About & policy"' in r.text
    assert "https://as215932.net/" in r.text


def test_about_explains_the_service_record_privacy_model(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/about")
    body = r.text
    assert "operational service and payment records" in body
    assert "identity profiles" in body
    assert 'href="/privacy"' in body
    # Privacy is factual context, not the old identity-negation slogan.
    assert "No email. No phone. No PII." not in body


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
    assert "/v1/payments/networks" in r.text


# --- homepage uses live runtime ---


def test_homepage_renders_live_runtime_p50(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Runtime latency belongs in the homepage infrastructure panel."""
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
    assert "API p50" in r.text
    assert "17ms" in r.text
    assert "api · 17ms" not in r.text
    # avg_provision_seconds shows up in the homepage hero stat
    assert "71s" in r.text or "~71s" in r.text


def test_homepage_falls_back_when_runtime_unavailable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/stats/runtime").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/")
    assert r.status_code == 200
    # The runtime panel stays honest without turning the site-status control
    # into an API-latency indicator.
    assert "API p50" in r.text
    assert "api ·" not in r.text
    assert "—" in r.text


def test_base_header_status_is_independent_of_runtime_latency(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The header reports service health, not a misleading latency sample."""
    mocked_api.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
        "api_p50_ms": 99,
        "api_p50_source": "api-process-local-rolling-window",
        "api_p50_sample_count": 1,
        "build_queue": 0,
        "live_vms": 0,
        "avg_provision_seconds": None,
        "updated_at": "2026-05-17T00:00:00+00:00",
    }))
    r = client.get("/about")
    assert r.status_code == 200
    assert 'popovertarget="service-status-popover"' in r.text
    assert "99ms" not in r.text


# --- sitemap updates ---


def test_sitemap_includes_about_and_faq(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    assert "https://hyrule.host/about" in body
    assert "https://hyrule.host/transparency" not in body
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
    assert "Native VM checkout rails currently enabled: BTC, XMR" in text


def test_build_llms_txt_keeps_privacy_as_agent_model_context() -> None:
    """No-KYC remains factual context without displacing the agent workflow."""
    for nets in (None, [], [{"key": "base", "display_name": "Base", "caip2": "eip155:8453"}]):
        text = build_llms_txt(networks=nets)
        assert "## Agent purchase model" in text
        assert "No-KYC ordering" in text
        assert "## Anonymity guarantees" not in text
        assert "No email. No phone. No PII." not in text


# --- header nav distinguishes logged-in vs anon ---


def test_header_nav_shows_login_when_no_session(client: TestClient) -> None:
    r = client.get("/")
    # No hyr_sess cookie → Login link in nav
    assert ">Login<" in r.text or ">Login</a>" in r.text


def test_header_nav_shows_dashboard_when_session_cookie_present(client: TestClient) -> None:
    r = client.get("/", cookies={"hyr_sess": "stub-session"})
    assert ">Dashboard<" in r.text or ">Dashboard</a>" in r.text
