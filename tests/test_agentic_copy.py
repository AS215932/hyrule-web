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
