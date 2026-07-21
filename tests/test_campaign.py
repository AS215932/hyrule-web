"""Outcome campaign, Agent Mail, and customer-journey public pages."""

from __future__ import annotations

import httpx
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

    assert "$2.34" in response.text
    assert "$99.00" not in response.text


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
    assert "## Agent Mail (live)" not in build_llms_txt(
        [base], payments_live=False, mail=mail
    )
    assert "## Agent Mail (live)" in build_llms_txt([base], mail=mail)


def test_desktop_navigation_waits_for_full_width() -> None:
    from pathlib import Path

    css = Path("frontend/src/styles/monochrome.css").read_text()
    assert "@media (width < 1280px)" in css
    assert "@media (width >= 1280px)" in css
    assert "@media (width < 1080px)" not in css
