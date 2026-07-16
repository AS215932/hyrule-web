from __future__ import annotations

import json

import httpx
import pytest
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
    assert "/login?next=/domains/checkout/dq_example123456789" in response.text
    assert "/signup?next=/domains/checkout/dq_example123456789" in response.text


def test_domain_checkout_excludes_non_evm_payment_networks(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/quotes/dq_example123456789").mock(
        return_value=httpx.Response(200, json=quote())
    )
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(200, json={"account_id": "acct"}))
    mocked_api.get("/v1/payments/networks").mock(
        return_value=httpx.Response(
            200,
            json={
                "networks": [
                    {
                        "key": "base",
                        "display_name": "Base",
                        "family": "evm",
                        "asset": "USDC",
                    },
                    {
                        "key": "solana",
                        "display_name": "Solana",
                        "family": "svm",
                        "asset": "USDC",
                    },
                ],
                "native": [],
            },
        )
    )

    response = client.get("/domains/checkout/dq_example123456789")

    assert response.status_code == 200
    assert '<option value="base">Base · USDC</option>' in response.text
    assert "Solana" not in response.text


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


def test_domain_order_status_preserves_path_across_login(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/orders/do_expired_session").mock(
        return_value=httpx.Response(401)
    )

    response = client.get(
        "/domains/orders/do_expired_session",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/login?next=%2Fdomains%2Forders%2Fdo_expired_session"
    )


def test_domain_order_status_reports_backend_outage_instead_of_redirecting(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/orders/do_api_outage").mock(
        side_effect=httpx.ConnectError("backend unavailable")
    )

    response = client.get(
        "/domains/orders/do_api_outage",
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert "temporarily unreachable" in response.text
    assert "location" not in response.headers


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
            "idempotency_key": "dns-form-retry-key",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    request = route.calls.last.request
    assert request.headers["if-match"] == "3"
    assert request.headers["idempotency-key"] == "dns-form-retry-key"
    assert json.loads(request.content)["changes"][0]["rrset"]["values"] == ["192.0.2.44"]


def test_domain_dns_editor_rejects_invalid_fields_without_backend_call(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/domains/example.dev/dns/changesets").mock(
        return_value=httpx.Response(200, json={"revision": 4})
    )
    response = client.post(
        "/dashboard/domains/example.dev/dns",
        data={
            "revision": "3",
            "action": "overwrite",
            "name": "bad name",
            "record_type": "BOGUS",
            "ttl": "59",
            "values": "value",
            "idempotency_key": "dns-form-retry-key",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "DNS%20change%20action%20is%20invalid" in response.headers["location"]
    assert not route.called


def test_domain_dns_delete_ignores_upsert_ttl_limits(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/domains/example.dev/dns/changesets").mock(
        return_value=httpx.Response(200, json={"revision": 4})
    )

    response = client.post(
        "/dashboard/domains/example.dev/dns",
        data={
            "revision": "3",
            "action": "delete",
            "name": "legacy",
            "record_type": "A",
            "ttl": "30",
            "values": "192.0.2.44",
            "idempotency_key": "dns-delete-form-key",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    change = json.loads(route.calls.last.request.content)["changes"][0]
    assert change == {
        "action": "delete",
        "rrset": {
            "name": "legacy",
            "type": "A",
            "values": ["192.0.2.44"],
        },
    }


def test_domain_nameserver_mutation_validates_and_reuses_form_key(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.put("/v1/domains/example.dev/nameservers").mock(
        return_value=httpx.Response(202, json={"operation_id": "dop_ns"})
    )
    response = client.post(
        "/dashboard/domains/example.dev/nameservers",
        data={
            "mode": "external",
            "nameservers": "NS1.EXAMPLE.NET.\nns2.example.net",
            "idempotency_key": "nameserver-form-key",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    request = route.calls.last.request
    assert request.headers["idempotency-key"] == "nameserver-form-key"
    assert json.loads(request.content) == {
        "mode": "external",
        "nameservers": ["ns1.example.net", "ns2.example.net"],
    }

    invalid = client.post(
        "/dashboard/domains/example.dev/nameservers",
        data={
            "mode": "external",
            "nameservers": "only-one.example.net",
            "idempotency_key": "another-nameserver-key",
        },
        follow_redirects=False,
    )
    assert "requires%20between%202%20and%2013" in invalid.headers["location"]
    assert len(route.calls) == 1


def test_domain_dnssec_mutation_requires_valid_ds_and_reuses_form_key(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.put("/v1/domains/example.dev/dnssec").mock(
        return_value=httpx.Response(202, json={"operation_id": "dop_ds"})
    )
    response = client.post(
        "/dashboard/domains/example.dev/dnssec",
        data={
            "mode": "external",
            "ds_records": "12345 13 2 aabbccddeeff0011",
            "idempotency_key": "dnssec-form-key",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    request = route.calls.last.request
    assert request.headers["idempotency-key"] == "dnssec-form-key"
    assert json.loads(request.content)["ds_records"] == [
        {"key_tag": 12345, "algorithm": 13, "digest_type": 2, "digest": "AABBCCDDEEFF0011"}
    ]

    invalid = client.post(
        "/dashboard/domains/example.dev/dnssec",
        data={
            "mode": "external",
            "ds_records": "",
            "idempotency_key": "another-dnssec-key",
        },
        follow_redirects=False,
    )
    assert "requires%20at%20least%20one" in invalid.headers["location"]
    assert len(route.calls) == 1


@pytest.mark.parametrize(
    ("status", "location"),
    [(401, "/login"), (404, "/dashboard")],
)
def test_domain_dashboard_redirects_on_detail_failure(
    client: TestClient,
    mocked_api: respx.MockRouter,
    status: int,
    location: str,
) -> None:
    mocked_api.get("/v1/domains/example.dev").mock(return_value=httpx.Response(status))

    response = client.get("/dashboard/domains/example.dev", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == location


def test_domain_dashboard_reports_detail_api_outage_instead_of_redirecting(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/example.dev").mock(
        side_effect=httpx.ConnectError("backend unavailable")
    )

    response = client.get("/dashboard/domains/example.dev", follow_redirects=False)

    assert response.status_code == 503
    assert "temporarily unreachable" in response.text
    assert "location" not in response.headers


def test_domain_dashboard_handles_zone_and_wallet_outages(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/domains/example.dev").mock(
        return_value=httpx.Response(200, json=detail())
    )
    mocked_api.get("/v1/domains/example.dev/dns").mock(return_value=httpx.Response(503))
    mocked_api.get("/v1/auth/wallet").mock(return_value=httpx.Response(503))

    response = client.get("/dashboard/domains/example.dev")

    assert response.status_code == 200
    assert "Add or replace an RRset" not in response.text
    assert 'data-wallet=""' in response.text


def test_domain_dashboard_renders_stable_delete_form_key(
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
                "records": [
                    {"name": "www", "type": "AAAA", "ttl": 300, "values": ["2001:db8::1"]}
                ],
                "dnssec_mode": "managed",
                "dnssec_status": "active",
            },
        )
    )

    response = client.get("/dashboard/domains/example.dev")

    assert response.status_code == 200
    assert response.text.count('name="idempotency_key"') == 4
    assert "2001:db8::1" in response.text


def test_domain_renewal_redirects_to_checkout_or_detail(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/domains/quotes").mock(
        return_value=httpx.Response(201, json=quote())
    )
    success = client.post(
        "/dashboard/domains/example.dev/renew", follow_redirects=False
    )
    assert success.headers["location"] == "/domains/checkout/dq_example123456789"
    assert json.loads(route.calls.last.request.content) == {
        "domain": "example.dev",
        "action": "renew",
    }

    mocked_api.post("/v1/domains/quotes").mock(
        return_value=httpx.Response(409, json={"detail": "Too early to renew."})
    )
    failure = client.post(
        "/dashboard/domains/example.dev/renew", follow_redirects=False
    )
    assert "Too%20early%20to%20renew" in failure.headers["location"]


@pytest.mark.parametrize(
    ("overrides", "notice"),
    [
        ({"idempotency_key": "short"}, "form%20expired"),
        ({"action": "replace"}, "action%20is%20invalid"),
        ({"name": "bad name"}, "record%20name%20is%20invalid"),
        ({"name": "www.*"}, "record%20name%20is%20invalid"),
        ({"record_type": "PTR"}, "type%20is%20not%20supported"),
        ({"ttl": "59"}, "TTL%20must%20be%20between"),
        ({"values": "\n"}, "At%20least%20one"),
    ],
)
def test_domain_dns_mutation_rejects_each_invalid_field(
    client: TestClient,
    mocked_api: respx.MockRouter,
    overrides: dict[str, str],
    notice: str,
) -> None:
    route = mocked_api.post("/v1/domains/example.dev/dns/changesets").mock(
        return_value=httpx.Response(200, json={"revision": 4})
    )
    data = {
        "revision": "3",
        "action": "upsert",
        "name": "www",
        "record_type": "A",
        "ttl": "300",
        "values": "192.0.2.44",
        "idempotency_key": "dns-form-retry-key",
        **overrides,
    }

    response = client.post(
        "/dashboard/domains/example.dev/dns", data=data, follow_redirects=False
    )

    assert response.status_code == 303
    assert notice in response.headers["location"]
    assert not route.called


@pytest.mark.parametrize(
    ("data", "notice"),
    [
        (
            {"mode": "managed", "idempotency_key": "short"},
            "form%20expired",
        ),
        (
            {"mode": "automatic", "idempotency_key": "nameserver-form-key"},
            "mode%20is%20invalid",
        ),
        (
            {
                "mode": "external",
                "nameservers": "not a hostname,ns2.example.net",
                "idempotency_key": "nameserver-form-key",
            },
            "valid%20hostname",
        ),
        (
            {
                "mode": "external",
                "nameservers": "ns1.example.net,NS1.EXAMPLE.NET.",
                "idempotency_key": "nameserver-form-key",
            },
            "must%20be%20unique",
        ),
    ],
)
def test_domain_nameserver_mutation_rejects_invalid_inputs(
    client: TestClient,
    mocked_api: respx.MockRouter,
    data: dict[str, str],
    notice: str,
) -> None:
    route = mocked_api.put("/v1/domains/example.dev/nameservers").mock(
        return_value=httpx.Response(202)
    )

    response = client.post(
        "/dashboard/domains/example.dev/nameservers",
        data=data,
        follow_redirects=False,
    )

    assert notice in response.headers["location"]
    assert not route.called


@pytest.mark.parametrize(
    ("data", "notice"),
    [
        ({"mode": "managed", "idempotency_key": "short"}, "form%20expired"),
        (
            {"mode": "automatic", "idempotency_key": "dnssec-form-key"},
            "mode%20is%20invalid",
        ),
        (
            {
                "mode": "external",
                "ds_records": "12345 13 2 not-hex",
                "idempotency_key": "dnssec-form-key",
            },
            "Each%20external%20DS%20line",
        ),
        (
            {
                "mode": "external",
                "ds_records": "\n".join(["1 13 2 AABBCCDDEEFF0011"] * 9),
                "idempotency_key": "dnssec-form-key",
            },
            "at%20most%208",
        ),
    ],
)
def test_domain_dnssec_mutation_rejects_invalid_inputs(
    client: TestClient,
    mocked_api: respx.MockRouter,
    data: dict[str, str],
    notice: str,
) -> None:
    route = mocked_api.put("/v1/domains/example.dev/dnssec").mock(
        return_value=httpx.Response(202)
    )

    response = client.post(
        "/dashboard/domains/example.dev/dnssec", data=data, follow_redirects=False
    )

    assert notice in response.headers["location"]
    assert not route.called


def test_domain_claim_redirects_for_success_and_failure(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/domains/example.dev/claim").mock(
        return_value=httpx.Response(200, json=detail())
    )
    success = client.post(
        "/dashboard/domains/claim",
        data={"domain": " example.dev ", "token": " claim-token "},
        follow_redirects=False,
    )
    assert success.headers["location"] == "/dashboard/domains/example.dev"

    mocked_api.post("/v1/domains/example.dev/claim").mock(
        return_value=httpx.Response(403)
    )
    failure = client.post(
        "/dashboard/domains/claim",
        data={"domain": "example.dev", "token": "bad-token"},
        follow_redirects=False,
    )
    assert failure.headers["location"] == "/dashboard?domain_claim=failed"


def test_domain_terms_and_navigation_are_public(client: TestClient) -> None:
    response = client.get("/terms")
    assert "Hyrule is the legal registrant" in response.text
    assert "Registrar auto-renew is disabled" in response.text
    home = client.get("/")
    assert 'href="/domains"' in home.text
