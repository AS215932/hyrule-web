from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

PRICE = {
    "provider_cost_usd": "10.00",
    "hyrule_fee_usd": "3.00",
    "tax_usd": "0.00",
    "total_usd": "13.00",
    "currency": "USD",
}


def quote() -> dict:
    return {
        "quote_id": "dq_example123456789",
        "domain": "example.dev",
        "action": "register",
        "period_years": 1,
        "price": PRICE,
        "available": True,
        "expires_at": "2026-07-15T10:15:00+00:00",
        "terms_version": "2026-07-15",
    }


def detail() -> dict:
    return {
        "domain": "example.dev",
        "status": "active",
        "expires_at": "2027-07-15T10:00:00+00:00",
        "renewal_notice_days": 60,
        "nameserver_mode": "managed",
        "nameservers": ["ns1.hyrule.host", "ns2.hyrule.host"],
        "dnssec_mode": "managed",
        "dnssec_status": "active",
        "registered_at": "2026-07-15T10:00:00+00:00",
        "provider_status": "ACT",
        "can_renew": True,
        "can_transfer": True,
        "linked_vm_id": None,
    }


def test_public_domain_search_and_separate_prices(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/check", params={"domain": "example.dev"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "domain": "example.dev",
                "eligible": True,
                "available": True,
                "premium": False,
                "reason": None,
                "registration": PRICE,
                "renewal": {**PRICE, "total_usd": "15.00"},
                "checked_at": "2026-07-15T10:00:00+00:00",
            },
        )
    )
    response = client.get("/domains?domain=example.dev")
    assert response.status_code == 200
    assert "example.dev" in response.text
    assert "register · 1 year" in response.text
    assert "$13.00" in response.text
    assert "$15.00" in response.text
    assert "ns1.hyrule.host" in response.text


def test_domain_quote_redirects_to_account_checkout(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/domains/quotes").mock(
        return_value=httpx.Response(201, json=quote())
    )
    response = client.post(
        "/domains/quote",
        data={"domain": "example.dev", "action": "register"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/domains/checkout/dq_example123456789"
    assert json.loads(route.calls.last.request.content) == {
        "domain": "example.dev",
        "action": "register",
    }


def test_domain_checkout_requires_account_before_payment(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/quotes/dq_example123456789").mock(
        return_value=httpx.Response(200, json=quote())
    )
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(401))
    response = client.get("/domains/checkout/dq_example123456789")
    assert response.status_code == 200
    assert "Log in or create an account before paying" in response.text
    assert "Pay and place order" not in response.text


def test_domain_order_status_is_account_scoped(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/orders/do_123456789").mock(
        return_value=httpx.Response(
            200,
            json={
                "order_id": "do_123456789",
                "domain": "example.dev",
                "action": "register",
                "status": "active",
                "amount_usd": "13.00",
                "payment_method": "usdc",
                "payment": None,
                "operation_id": "dop_123",
                "vm_id": None,
                "error_code": None,
                "created_at": "2026-07-15T10:00:00+00:00",
                "updated_at": "2026-07-15T10:01:00+00:00",
            },
        )
    )
    response = client.get("/domains/orders/do_123456789")
    assert response.status_code == 200
    assert "Manage DNS and renewal" in response.text
    assert "do_123456789" in response.text


def test_native_domain_payment_instructions_survive_reload(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/orders/do_native123").mock(
        return_value=httpx.Response(
            200,
            json={
                "order_id": "do_native123",
                "domain": "example.dev",
                "action": "register",
                "status": "awaiting_payment",
                "amount_usd": "13.00",
                "payment_method": "btc",
                "payment": {
                    "intent_id": "intent-123",
                    "asset": "BTC",
                    "address": "bc1qexampledepositaddress",
                    "amount_crypto": "0.00012345",
                    "amount_usd": "13.00",
                    "qr_code_uri": "bitcoin:bc1qexampledepositaddress?amount=0.00012345",
                    "rate_valid_until": "2026-07-15T10:15:00+00:00",
                    "expires_at": "2026-07-15T11:00:00+00:00",
                },
                "operation_id": None,
                "vm_id": None,
                "error_code": None,
                "created_at": "2026-07-15T10:00:00+00:00",
                "updated_at": "2026-07-15T10:01:00+00:00",
            },
        )
    )
    response = client.get("/domains/orders/do_native123")
    assert response.status_code == 200
    assert "Send exactly 0.00012345 BTC" in response.text
    assert "bc1qexampledepositaddress" in response.text
    assert 'data-copy-target="domain-deposit-address"' in response.text


def test_domain_dns_editor_forwards_revision_and_idempotency(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/example.dev").mock(
        return_value=httpx.Response(200, json=detail())
    )
    mocked_api.get("/v1/domains/example.dev/dns").mock(
        return_value=httpx.Response(
            200,
            json={
                "domain": "example.dev",
                "revision": 3,
                "records": [],
                "dnssec_mode": "managed",
                "dnssec_status": "active",
            },
        )
    )
    response = client.get("/dashboard/domains/example.dev")
    assert response.status_code == 200
    assert "revision 3" in response.text
    assert "Apply changeset" in response.text

    route = mocked_api.post("/v1/domains/example.dev/dns/changesets").mock(
        return_value=httpx.Response(200, json={"revision": 4})
    )
    changed = client.post(
        "/dashboard/domains/example.dev/dns",
        data={
            "revision": "3",
            "action": "upsert",
            "name": "www",
            "record_type": "A",
            "ttl": "300",
            "values": "192.0.2.44",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    request = route.calls.last.request
    assert request.headers["if-match"] == "3"
    assert request.headers["idempotency-key"]
    assert json.loads(request.content)["changes"][0]["rrset"]["values"] == ["192.0.2.44"]


def test_domain_terms_and_navigation_are_public(client: TestClient) -> None:
    response = client.get("/terms")
    assert "Hyrule is the legal registrant" in response.text
    assert "Registrar auto-renew is disabled" in response.text
    home = client.get("/")
    assert 'href="/domains"' in home.text
