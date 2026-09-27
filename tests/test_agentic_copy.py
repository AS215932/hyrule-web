"""Issue #14 (Phase 5): homepage settlement-chain copy is driven from the live
/v1/payments/networks list (never hardcoded), and llms.txt lists the canonical
agent URLs.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

_NET = {
    "key": "base",
    "display_name": "Base",
    "caip2": "eip155:8453",
    "family": "evm",
    "chain_id": 8453,
    "asset": "USDC",
    "token_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "token_decimals": 6,
    "eip712_domain": {"name": "USD Coin", "version": "2"},
}


def test_homepage_chains_from_live_networks_not_hardcoded(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    # Default mocked_api advertises Base only (matches production today).
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "Base" in body
    # The old hardcoded "Base, Polygon, Arbitrum" copy must be gone — only the
    # live chain(s) should appear.
    assert "Polygon" not in body
    assert "Arbitrum" not in body


def test_homepage_reflects_multiple_live_chains(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/payments/networks").mock(
        return_value=httpx.Response(
            200,
            json={"networks": [_NET, {**_NET, "key": "polygon", "display_name": "Polygon"}]},
        )
    )
    r = client.get("/")
    assert "Base" in r.text
    assert "Polygon" in r.text


def test_homepage_does_not_claim_payment_rails_when_catalog_is_unavailable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/payments/networks").mock(
        side_effect=httpx.ConnectError("catalog unavailable")
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Live settlement rails unavailable" in response.text
    assert "enabled EVM chains" not in response.text


def test_llms_txt_lists_canonical_urls(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/llms.txt")
    assert r.status_code == 200
    body = r.text
    for url in (
        "https://cloud.hyrule.host/openapi.json",
        "https://cloud.hyrule.host/.well-known/x402.json",
        "https://cloud.hyrule.host/v1/products/vms",
        "https://cloud.hyrule.host/v1/vm/quote",
        "https://cloud.hyrule.host/v1/vm/create",
    ):
        assert url in body, f"llms.txt missing canonical URL {url}"


def _openapi_with_domains() -> dict[str, object]:
    """An enabled OpenAPI document that DOES advertise a payable domain order."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Hyrule enabled x402 API", "version": "test"},
        "paths": {
            "/v1/domains/orders": {
                "post": {
                    "operationId": "create_domain_order",
                    "summary": "Place a domain registration or renewal",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"},
                                "example": {"domain": "example.dev"},
                            }
                        }
                    },
                    "responses": {
                        "202": {"content": {"application/json": {"schema": {"type": "object"}}}}
                    },
                    "x-payment-info": {
                        "price": {"mode": "dynamic", "currency": "USD", "min": "6.00"}
                    },
                }
            },
        },
    }


def test_llms_txt_does_not_market_the_deferred_domain_product(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Live evidence from the first dogfood run: `/v1/domains/check` and
    `/v1/domains/tlds` answer 503 (registrar provider unconfigured) and the
    API's own OpenAPI says domain registration is deferred from the launch
    catalog — while llms.txt still sold it. The default conftest OpenAPI
    fixture advertises no domain operation, which is production today."""
    r = client.get("/llms.txt")
    assert r.status_code == 200
    body = r.text
    for url in (
        "https://cloud.hyrule.host/v1/domains/openapi.json",
        "https://cloud.hyrule.host/v1/domains/check?domain=example.dev",
        "https://cloud.hyrule.host/v1/domains/quotes",
        "https://cloud.hyrule.host/v1/domains/orders",
        "[Search domains](https://hyrule.host/domains)",
    ):
        assert url not in body, f"llms.txt still advertises deferred domain URL {url}"
    # And it says so, rather than silently dropping the product.
    assert "Not yet launched" in body
    assert "deferred from the current" in body


def test_llms_txt_advertises_domains_again_once_the_catalog_enables_them(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """No hardcoded launch date: the copy follows the enabled x402 catalog."""
    mocked_api.get("/openapi.json").mock(
        return_value=httpx.Response(200, json=_openapi_with_domains())
    )
    body = client.get("/llms.txt").text
    assert "[Search domains](https://hyrule.host/domains)" in body
    assert "https://cloud.hyrule.host/v1/domains/orders" in body
    assert "Not yet launched" not in body


def test_llms_txt_x402_manifest_reference_is_absolute(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """A relative `/.well-known/x402.json` resolves against hyrule.host, where
    it used to 404 — the discovery dead-end this document caused."""
    body = client.get("/llms.txt").text
    assert "in the x402 manifest at\n  https://cloud.hyrule.host/.well-known/x402.json" in body
    assert "schemas in `/.well-known/x402.json`" not in body


def test_llms_txt_fallback_never_markets_domains_when_discovery_fails(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Fail-closed: an unknown catalog state is not a launched product."""
    mocked_api.get("/openapi.json").mock(side_effect=httpx.ConnectError("offline"))
    body = client.get("/llms.txt").text
    # No callable domain URL is offered; only the plain "deferred" note, which
    # names the endpoint family without pointing agents at a buyable URL.
    assert "https://cloud.hyrule.host/v1/domains" not in body
    assert "[Search domains]" not in body
    assert "Not yet launched" in body


def test_marketing_pages_do_not_price_the_deferred_domain_product(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """[[feedback_ship_features_before_copy]]: marketing copy describes only
    live features, built from live config rather than a hardcoded list."""
    home = client.get("/")
    assert home.status_code == 200
    assert "not yet launched" in home.text

    services = client.get("/services")
    assert services.status_code == 200
    assert "not currently confirmed by the enabled OpenAPI catalog" in services.text
    assert "registration is deferred from the launch catalog" in services.text


def test_marketing_pages_price_domains_when_the_catalog_enables_them(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/openapi.json").mock(
        return_value=httpx.Response(200, json=_openapi_with_domains())
    )
    home = client.get("/")
    assert "$6.00+" in home.text
    assert "not yet launched" not in home.text

    services = client.get("/services")
    assert "/v1/domains/orders" in services.text
    assert "registration price varies by TLD" in services.text
