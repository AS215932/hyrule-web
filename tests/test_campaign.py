"""Outcome campaign, Agent Mail, and customer-journey public pages."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient


def test_agent_mail_fails_closed_when_catalog_is_not_ready(client: TestClient) -> None:
    response = client.get("/agent-mail")

    assert response.status_code == 200
    assert "Launch gated" in response.text
    assert "Email accounts built for agents" in response.text
    assert "no public smtp submission" in response.text.lower()
    assert "/v1/mail/products" in response.text


def test_agent_mail_shows_available_only_from_live_catalog(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "backend": "dedicated Stalwart",
                "products": [
                    {
                        "id": "agent-mail-hosted",
                        "title": "Agent mailbox on @agentmail.hyrule.host",
                        "price_usd": "1.00",
                        "billing": "30 days, no auto-renew",
                        "available": True,
                        "constraints": ["API-only submission and retrieval"],
                    }
                ],
            },
        )
    )

    response = client.get("/agent-mail")

    assert response.status_code == 200
    assert "Available" in response.text
    assert "$1.00" in response.text


def test_agent_mail_fails_closed_without_an_available_product(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-hosted",
                        "price_usd": "1.00",
                        "available": False,
                    }
                ],
            },
        )
    )

    response = client.get("/agent-mail")

    assert "Launch gated" in response.text
    assert "Not currently offered" in response.text


def test_agent_mail_honors_catalog_wide_availability(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": False,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-hosted",
                        "price_usd": "7.77",
                        "available": True,
                    }
                ],
            },
        )
    )

    response = client.get("/agent-mail")

    assert "Launch gated" in response.text
    assert "$7.77" not in response.text


def test_agent_mail_selects_hosted_price_by_product_id(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-domain-bundle",
                        "price_usd": "99.00",
                        "available": True,
                    },
                    {
                        "id": "agent-mail-hosted",
                        "price_usd": "2.34",
                        "available": True,
                    },
                ],
            },
        )
    )

    response = client.get("/agent-mail")

    assert "$2.34 <small>/ 30 days</small>" in response.text
    assert "live domain quote + $99.00" in response.text


def test_services_uses_the_live_hosted_product_price(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-hosted",
                        "price_usd": "2.34",
                        "available": True,
                    }
                ],
            },
        )
    )
    mocked_api.get("/v1/mail/pricing").mock(
        return_value=httpx.Response(200, json={"outbound_message_usd": "0.07"})
    )

    response = client.get("/services")

    assert "$2.34 / 30 days + $0.07 per accepted outbound" in response.text
    assert "$1 / 30 days" not in response.text


def test_mail_pages_withhold_unconfirmed_outbound_pricing(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-hosted",
                        "price_usd": "1.00",
                        "available": True,
                    }
                ],
            },
        )
    )
    mocked_api.get("/v1/mail/pricing").mock(return_value=httpx.Response(503))

    services = client.get("/services")

    assert "live outbound fee unavailable" in services.text
    assert "$0.01 per accepted outbound" not in services.text

    from hyrule_web.app import _MAIL_PRICING_CACHE

    _MAIL_PRICING_CACHE.update(value=None, expires_at=0.0, retry_at=0.0)
    agent_mail = client.get("/agent-mail")
    assert "Live send fee unavailable" in agent_mail.text
    assert "$0.01" not in agent_mail.text


def test_services_does_not_advertise_hosted_mail_when_only_another_product_is_live(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-custom",
                        "price_usd": "8.76",
                        "available": True,
                    }
                ],
            },
        )
    )

    response = client.get("/services")

    assert "Hosted mailbox not currently offered" in response.text
    assert "$8.76 / 30 days" not in response.text


@pytest.mark.parametrize(
    "backend_response",
    [
        pytest.param(httpx.Response(503), id="backend-unavailable"),
        pytest.param(
            httpx.Response(200, json={"available": True, "products": "invalid"}),
            id="invalid-catalog",
        ),
    ],
)
def test_mail_catalog_failures_are_negatively_cached_for_a_short_window(
    client: TestClient,
    mocked_api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    backend_response: httpx.Response,
) -> None:
    import hyrule_web.app as app_module

    clock = [1_000.0]
    monkeypatch.setattr(app_module, "time", SimpleNamespace(time=lambda: clock[0]))
    route = mocked_api.get("/v1/mail/products").mock(return_value=backend_response)

    assert "Launch gated" in client.get("/agent-mail").text
    assert "Launch gated" in client.get("/agent-mail").text
    assert route.call_count == 1

    clock[0] += app_module._MAIL_PRODUCTS_NEGATIVE_TTL_SECONDS + 1
    assert "Launch gated" in client.get("/agent-mail").text
    assert route.call_count == 2


def test_mail_catalog_negative_ttl_starts_after_a_slow_failure(
    client: TestClient,
    mocked_api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hyrule_web.app as app_module

    clock = [2_000.0]
    monkeypatch.setattr(app_module, "time", SimpleNamespace(time=lambda: clock[0]))
    original_fetch = app_module._fetch_api

    async def slow_fetch(request, path):
        if path == "/v1/mail/products":
            clock[0] += 30
        return await original_fetch(request, path)

    monkeypatch.setattr(app_module, "_fetch_api", slow_fetch)
    route = mocked_api.get("/v1/mail/products").mock(return_value=httpx.Response(503))

    assert "Launch gated" in client.get("/agent-mail").text
    assert "Launch gated" in client.get("/agent-mail").text
    assert route.call_count == 1


def test_domain_bundle_surfaces_require_the_matching_live_product(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    hosted_only = {
        "available": True,
        "terms_version": "2026-08-04",
        "products": [
            {
                "id": "agent-mail-hosted",
                "price_usd": "1.00",
                "available": True,
            }
        ],
    }
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(200, json=hosted_only)
    )

    assert "Not currently offered" in client.get("/agent-mail").text

    from hyrule_web.app import _MAIL_PRODUCTS_CACHE

    _MAIL_PRODUCTS_CACHE.update(value=None, expires_at=0.0, retry_at=0.0)
    assert "Canary pending" in client.get(
        "/blog/agent-email-domain-deliverability"
    ).text

    _MAIL_PRODUCTS_CACHE.update(value=None, expires_at=0.0, retry_at=0.0)
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                **hosted_only,
                "products": [
                    *hosted_only["products"],
                    {
                        "id": "agent-mail-domain-bundle",
                        "price_usd": "1.25",
                        "available": True,
                    },
                ],
            },
        )
    )

    assert "live domain quote + $1.25" in client.get("/agent-mail").text
    _MAIL_PRODUCTS_CACHE.update(value=None, expires_at=0.0, retry_at=0.0)
    assert "Catalog available" in client.get(
        "/blog/agent-email-domain-deliverability"
    ).text


def test_blog_lists_three_outcome_journeys(client: TestClient) -> None:
    response = client.get("/blog")

    assert response.status_code == 200
    for path in (
        "/blog/explain-broken-website-tls",
        "/blog/agent-email-domain-deliverability",
        "/blog/deploy-fresh-vm",
    ):
        assert path in response.text
    assert "Canaries pending" in response.text
    assert "One controlled proof budget" in response.text


def test_each_journey_publishes_the_required_proof_contract(client: TestClient) -> None:
    for path in (
        "/blog/explain-broken-website-tls",
        "/blog/agent-email-domain-deliverability",
        "/blog/deploy-fresh-vm",
    ):
        response = client.get(path)
        assert response.status_code == 200
        for needle in (
            "Exact prompt",
            "Runnable command",
            "Redacted real-result shape",
            "Expected cost",
            "Elapsed contract",
            "Coinbase Bazaar MCP",
            "OpenClaw",
            "Generic Agent Skills",
            "Canary pending",
        ):
            assert needle in response.text, f"{path} missing {needle}"
        assert "openclaw skills install @as215932/" in response.text


def test_vm_journey_opens_ssh_plus_declared_workload_ports(client: TestClient) -> None:
    response = client.get("/blog/deploy-fresh-vm")

    assert "&#34;open_ports&#34;:[22,&lt;WORKLOAD_PORTS&gt;]" in response.text
    assert "&#34;open_ports&#34;:[80,443]" not in response.text
    assert "comma-separated numeric ports" in response.text


def test_agent_mail_journey_combines_identity_and_deliverability(client: TestClient) -> None:
    response = client.get("/blog/agent-email-domain-deliverability")

    assert response.status_code == 200
    for needle in (
        "one atomic domain-plus-mailbox x402 payment",
        "MX, SPF, DKIM, DMARC, TLS-RPT, MTA-STS",
        "exact combined amount",
        "exactly one controlled message",
        "$26.10",
    ):
        assert needle in response.text


def test_agent_mail_journey_uses_live_activation_and_outbound_prices(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-domain-bundle",
                        "price_usd": "1.25",
                        "available": True,
                    }
                ],
            },
        )
    )
    mocked_api.get("/v1/mail/pricing").mock(
        return_value=httpx.Response(200, json={"outbound_message_usd": "0.07"})
    )

    detail = client.get("/blog/agent-email-domain-deliverability")
    listing = client.get("/blog")

    expected = (
        "Live one-year domain quote + $1.25 Agent Mail activation + "
        "$0.07 controlled outbound"
    )
    assert expected in detail.text
    assert expected in listing.text
    assert "+ $1 activation + $0.01 controlled outbound" not in detail.text


def test_unknown_journey_is_not_found(client: TestClient) -> None:
    assert client.get("/blog/not-a-real-journey").status_code == 404


def test_sitemap_includes_campaign_pages(client: TestClient) -> None:
    text = client.get("/sitemap.xml").text
    for path in (
        "/agent-mail",
        "/blog",
        "/blog/explain-broken-website-tls",
        "/blog/agent-email-domain-deliverability",
        "/blog/deploy-fresh-vm",
    ):
        assert f"https://hyrule.host{path}" in text


def test_llms_advertises_mail_api_only_when_live(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    assert "## Agent Mail (live)" not in client.get("/llms.txt").text

    # Reset through a new live fetch after the first request populated the cache.
    from hyrule_web.app import _MAIL_PRODUCTS_CACHE

    _MAIL_PRODUCTS_CACHE.update(value=None, expires_at=0.0)
    mocked_api.get("/v1/mail/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "available": True,
                "terms_version": "2026-08-04",
                "products": [
                    {
                        "id": "agent-mail-hosted",
                        "title": "Agent mailbox",
                        "price_usd": "1.00",
                        "billing": "30 days",
                        "available": True,
                        "constraints": [],
                    }
                ],
            },
        )
    )

    text = client.get("/llms.txt").text
    assert "## Agent Mail (live)" in text
    assert "https://cloud.hyrule.host/v1/mail/products" in text


def test_llms_mail_requires_a_fresh_evm_payment_network() -> None:
    from hyrule_web.seo import build_llms_txt

    mail = {
        "available": True,
        "terms_version": "2026-08-04",
        "products": [{"id": "agent-mail-hosted", "available": True}],
    }
    base = {"family": "evm", "key": "base"}

    assert "## Agent Mail (live)" not in build_llms_txt(None, mail=mail)
    assert "## Agent Mail (live)" not in build_llms_txt([base], payments_live=False, mail=mail)
    assert "## Agent Mail (live)" in build_llms_txt([base], mail=mail)


def test_desktop_navigation_waits_for_full_width() -> None:
    from pathlib import Path

    css = Path("frontend/src/styles/monochrome.css").read_text()
    assert "@media (width < 1280px)" in css
    assert "@media (width >= 1280px)" in css
    assert "@media (width < 1080px)" not in css
