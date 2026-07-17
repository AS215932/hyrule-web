"""Issue #14: durable review flow — GET /order/review/{quote_id}.

The order form creates a quote and redirects here; this page re-renders from the
backend quote, so a mobile wallet handoff reload no longer loses the order.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient


def _quote(status: str = "created") -> dict:
    return {
        "quote_id": "q_test123",
        "status": status,
        "order_payload": {
            "os": "debian-13",
            "size": "md",
            "duration_days": 7,
            "ssh_pubkey": "ssh-ed25519 AAAA reviewer",
            "domain_mode": "auto",
            "domain": None,
            "resources": {"vcpu": 2, "ram_mb": 4096, "disk_gb": 20},
        },
        "resources": {"vcpu": 2, "ram_mb": 4096, "disk_gb": 20},
        "pricing": {
            "base_profile": "md",
            "base_label": "2C-4G-20G",
            "base_price_usd_day": "0.60",
            "addon_vcpu": 0,
            "addon_ram_mb": 0,
            "addon_disk_gb": 0,
            "addon_vcpu_usd_day": "0.00",
            "addon_ram_usd_day": "0.00",
            "addon_disk_usd_day": "0.00",
            "daily_price_usd": "0.60",
            "duration_days": 7,
            "total_usd": "4.20",
        },
        "amount_usd": "4.20",
        "currency": "USD",
        "accepted_payment_methods": {"evm": [], "native": []},
        "created_at": "2026-05-30T12:00:00Z",
        "expires_at": "2026-05-30T13:00:00Z",
    }


def test_review_renders_from_durable_quote(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/quote/q_test123").mock(
        return_value=httpx.Response(200, json=_quote())
    )
    r = client.get("/order/review/q_test123")
    assert r.status_code == 200
    body = r.text
    assert "debian-13" in body
    # md profile ($0.60/day) * 7 days
    assert "4.20" in body
    # quote_id is wired into the hidden form so payment.ts forwards it.
    assert 'name="quote_id" value="q_test123"' in body


def test_review_uses_backend_locked_amount_not_frontend_catalog(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    quote = _quote()
    quote["amount_usd"] = "9.73"
    mocked_api.get("/v1/vm/quote/q_locked").mock(
        return_value=httpx.Response(200, json=quote)
    )

    body = client.get("/order/review/q_locked").text

    assert "$9.73" in body
    assert "Pay $9.73 with wallet" in body


def test_review_survives_when_quoted_tier_leaves_live_catalog(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/products/vms").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {
                        "size": "xl",
                        "name": "Agent XL",
                        "vcpu": 4,
                        "ram_mb": 8192,
                        "disk_gb": 40,
                        "price_usd_day": "1.40",
                    }
                ]
            },
        )
    )
    mocked_api.get("/v1/vm/quote/q_retired").mock(
        return_value=httpx.Response(200, json=_quote())
    )

    response = client.get("/order/review/q_retired")

    assert response.status_code == 200
    assert "2C-4G-20G" in response.text
    assert "$4.20" in response.text


def test_review_unknown_quote_redirects_to_order(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/quote/q_missing").mock(
        return_value=httpx.Response(404, json={"detail": "Quote not found"})
    )
    r = client.get("/order/review/q_missing", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/order"


def test_review_expired_quote_shows_banner_and_disables_pay(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/quote/q_exp").mock(
        return_value=httpx.Response(200, json=_quote(status="expired"))
    )
    r = client.get("/order/review/q_exp")
    assert r.status_code == 200
    body = r.text
    assert "expired" in body.lower()
    assert "disabled" in body
