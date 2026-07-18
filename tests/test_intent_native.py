"""Block E: native crypto (BTC/XMR) frontend wiring.

Covers the static contract:
  - review.html includes the BTC/XMR/EVM tab radios, the deposit-render
    slot, and loads payment-native.js + payment-evm.js + payment.js
  - payment-native.js exposes window.HyrulePaymentNative.pay and POSTs to
    /api/v1/intent/create + GETs /api/v1/intent/{id}
  - The /api proxy forwards intent endpoints cleanly

Browser-side JS execution is out of scope (no headless browser); we cover
the wiring contract, not the actual scan loop.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

_STATIC = Path(__file__).parent.parent / "hyrule_web" / "static"
# Issue #14: the payment JS was migrated to TypeScript under frontend/src/ and is
# now bundled by Vite. The wiring contract below is checked against the TS source
# (the committed bundle is built from it).
_FRONTEND_SRC = Path(__file__).parent.parent / "frontend" / "src"


# --- Static asset shipping ---


def test_payment_native_js_exists_and_exports_native_driver():
    src = (_FRONTEND_SRC / "payment-native.ts").read_text()
    assert "window.HyrulePaymentNative" in src
    # Must call the two intent endpoints
    assert "/api/v1/intent/create" in src
    assert "/api/v1/intent/" in src
    # Must NOT call any /api/vm/create — that's the EVM path
    assert "/api/vm/create" not in src


def test_payment_dispatcher_routes_by_method():
    src = (_FRONTEND_SRC / "payment.ts").read_text()
    # Reads the payment-method radio set
    assert "payment-method" in src
    # Dispatches to both drivers: HyrulePayments.payWithEvm (Wave 3 EVM driver)
    # for USDC, HyrulePaymentNative for BTC/XMR.
    assert "HyrulePayments" in src
    assert "HyrulePaymentNative" in src
    # Has a render slot for the native deposit card
    assert "payment-native-render" in src


def test_payment_native_does_not_hardcode_chain_constants():
    """Same anti-hardcoding rule that applies to EVM — addresses + amounts
    come from the backend's /v1/intent/* response, never from JS."""
    src = (_FRONTEND_SRC / "payment-native.ts").read_text()
    # No magic Bitcoin address prefixes embedded (single check — the original
    # `... or ...` form was a tautology that always passed; Sourcery web#4).
    assert "bc1q" not in src
    # No hardcoded BTC/XMR rates
    assert "65000" not in src
    assert "160.00" not in src


# --- review.html wiring ---


def _post_order(client: TestClient) -> httpx.Response:
    return client.post(
        "/order/review",
        data={
            "os": "debian-13",
            "size": "sm",
            "duration": "7",
            "ssh_pubkey": "ssh-ed25519 AAAA...",
            "hostname": "",
            "domain_mode": "auto",
            "domain": "",
        },
    )


def test_review_page_includes_payment_method_tabs(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = _post_order(client)
    assert r.status_code == 200
    # Default catalog has no native rails, so only EVM is rendered.
    assert 'name="payment-method"' in r.text
    assert 'value="evm"' in r.text
    assert 'value="btc"' not in r.text
    assert 'value="xmr"' not in r.text
    # Native deposit render slot still exists for quotes/catalogs that enable it.
    assert 'id="payment-native-render"' in r.text


def test_review_quote_includes_native_tabs_when_backend_advertises_them(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/quote/q_native").mock(
        return_value=httpx.Response(
            200,
            json={
                "quote_id": "q_native",
                "status": "created",
                "order_payload": {
                    "duration_days": 7,
                    "size": "sm",
                    "os": "debian-13",
                    "ssh_pubkey": "ssh-ed25519 AAAA...",
                    "domain_mode": "auto",
                    "domain": None,
                    "open_ports": [22, 80, 443],
                    "resources": {"vcpu": 1, "ram_mb": 2048, "disk_gb": 20},
                },
                "resources": {"vcpu": 1, "ram_mb": 2048, "disk_gb": 20},
                "pricing": {
                    "base_profile": "sm",
                    "base_label": "1C-2G-20G",
                    "base_price_usd_day": "0.40",
                    "daily_price_usd": "0.40",
                    "duration_days": 7,
                    "total_usd": "2.80",
                },
                "amount_usd": "2.80",
                "currency": "USD",
                "accepted_payment_methods": {
                    "evm": [{"key": "base", "caip2": "eip155:8453", "asset": "USDC"}],
                    "native": ["BTC", "XMR"],
                },
                "created_at": "2026-05-30T12:00:00Z",
                "expires_at": "2026-05-30T12:15:00Z",
            },
        )
    )
    r = client.get("/order/review/q_native")
    assert r.status_code == 200
    assert 'value="btc"' in r.text
    assert 'value="xmr"' in r.text
    assert 'id="payment-native-render"' in r.text


def test_review_page_loads_native_script(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = _post_order(client)
    # Issue #14: the native driver is bundled into the payment entry, loaded via
    # the Vite manifest (vite_asset('payment')) rather than a standalone script.
    assert "/static/dist/assets/payment-" in r.text


# --- /api proxy forwards intent endpoints ---


def test_proxy_forwards_intent_create(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/intent/create").mock(
        return_value=httpx.Response(200, json={
            "intent_id": "abc-123",
            "asset": "BTC",
            "address": "bc1qtest",
            "amount_crypto": "0.00001",
            "status": "CREATED",
            "expires_at": "2026-05-17T01:00:00Z",
            "qr_code_uri": "bitcoin:bc1qtest?amount=0.00001",
        })
    )
    r = client.post(
        "/api/v1/intent/create",
        json={
            "asset": "BTC",
            "client_order_id": "client-1",
            "order_payload": {
                "duration_days": 1,
                "size": "xs",
                "os": "debian-13",
                "ssh_pubkey": "ssh-ed25519 AAAA",
            },
        },
    )
    assert r.status_code == 200
    assert r.json()["intent_id"] == "abc-123"
    assert route.called


def test_proxy_forwards_intent_status_with_provisioned_token(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/intent/abc-123").mock(
        return_value=httpx.Response(200, json={
            "intent_id": "abc-123",
            "asset": "BTC",
            "address": "bc1qtest",
            "amount_crypto": "0.00001",
            "status": "PROVISIONED",
            "vm_id": "vm_xyz",
            "management_token": "hyr_vm_revealed",
            "management_url": "http://api.hyrule.host/v1/vm/vm_xyz?token=hyr_vm_revealed",
            "expires_at": "2026-05-17T01:00:00Z",
        })
    )
    r = client.get("/api/v1/intent/abc-123")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PROVISIONED"
    assert body["management_token"] == "hyr_vm_revealed"
    assert body["vm_id"] == "vm_xyz"


def test_proxy_strips_v1_prefix_for_intent_paths(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The proxy historically accepted /api/<path> too (v1/ optional)."""
    route = mocked_api.get("/v1/intent/abc").mock(return_value=httpx.Response(200, json={}))
    client.get("/api/intent/abc")
    assert route.called
