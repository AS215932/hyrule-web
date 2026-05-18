"""Block C: chain selector + payment-evm.js dispatcher integration.

These tests verify the static contract:
  - review.html includes the hidden order-data form, chain selector, pay
    button, and the two script tags (payment-evm.js, payment.js)
  - The /api proxy routes /v1/payments/networks correctly
  - payment.js's expectations are met by the rendered review HTML

Browser-side JS execution is out of scope for these tests (no headless
browser); we cover the wiring contract, not the wallet flow itself.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

_STATIC = Path(__file__).parent.parent / "hyrule_web" / "static"


# --- Static asset shipping ---


def test_payment_evm_js_exists_and_exports_HyrulePaymentEVM():
    src = (_STATIC / "payment-evm.js").read_text()
    assert "window.HyrulePaymentEVM" in src
    assert "pay:" in src or "pay :" in src


def test_payment_svm_js_exists_and_exports_HyrulePaymentSVM():
    """Block H: Solana driver mirrors the EVM driver's contract."""
    src = (_STATIC / "payment-svm.js").read_text()
    assert "window.HyrulePaymentSVM" in src
    assert "pay:" in src or "pay :" in src
    # Detects all three target wallets
    assert "phantom" in src.lower()
    assert "solflare" in src.lower()
    assert "backpack" in src.lower()
    # Uses signTransaction (not signAndSendTransaction — facilitator submits)
    assert "signTransaction" in src
    # Loads heavy ESM deps from CDN to keep EVM-only checkout zero-cost
    assert "@solana/web3.js" in src
    assert "@solana/spl-token" in src


def test_payment_svm_uses_backend_supplied_metadata():
    """Block H: payment-svm.js must read mint / decimals / pay_to from the
    402 accepts entry, never hardcode them (feedback_verified_payment_chains)."""
    src = (_STATIC / "payment-svm.js").read_text()
    # No USDC mainnet mint hardcoded
    assert "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" not in src
    # Reads from network/accept arguments
    assert "accept.token_address" in src
    assert "accept.pay_to" in src
    assert "network.rpc_url" in src
    # Family-guard rejects mis-routed responses
    assert 'accept.family !== "svm"' in src or "accept.family !== 'svm'" in src


def test_payment_dispatcher_routes_by_family():
    """Block H: payment.js dispatches to the SVM driver when network.family=='svm'."""
    src = (_STATIC / "payment.js").read_text()
    assert "network.family" in src
    assert "HyrulePaymentSVM" in src
    # Both drivers wired via the same call shape
    assert "HyrulePaymentEVM" in src
    # Family-based routing decision
    assert "svm" in src


def test_payment_dispatcher_loads_networks_from_api_not_hardcoded():
    src = (_STATIC / "payment.js").read_text()
    # The dispatcher MUST call the networks endpoint
    assert "/api/v1/payments/networks" in src
    # And MUST NOT hardcode chain-specific constants (per
    # feedback_verified_payment_chains.md)
    assert "0x833589" not in src, "Base USDC contract leaked into dispatcher"
    assert "BASE_CHAIN_ID" not in src
    # The chain selector binding is wired
    assert "payment-chain" in src


def test_payment_evm_uses_caller_supplied_network_metadata():
    """payment-evm.js must read chain_id / token_address / eip712_domain from
    the network object passed in, not from hardcoded constants."""
    src = (_STATIC / "payment-evm.js").read_text()
    # No hardcoded Base values
    assert "0x833589" not in src
    assert "8453" not in src
    # Reads from network argument
    assert "network.chain_id" in src
    assert "network.token_address" in src
    assert "network.eip712_domain" in src
    assert "network.rpc_url" in src


# --- review.html wiring ---


def test_review_page_includes_chain_selector_and_pay_button(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """A submitted order renders review.html containing the new payment widgets."""
    r = client.post(
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
    assert r.status_code == 200
    assert 'id="payment-chain"' in r.text
    assert 'id="pay-btn"' in r.text
    assert 'id="payment-status"' in r.text
    assert 'id="order-data"' in r.text
    # All payment drivers must be loaded (dispatcher routes by family/method)
    assert "/static/payment-evm.js" in r.text
    assert "/static/payment-svm.js" in r.text
    assert "/static/payment.js" in r.text


def test_review_page_hidden_form_mirrors_order_fields(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.post(
        "/order/review",
        data={
            "os": "alpine-3.21",
            "size": "md",
            "duration": "14",
            "ssh_pubkey": "ssh-ed25519 KEY_HERE",
            "hostname": "myhost",
            "domain_mode": "auto",
            "domain": "",
        },
    )
    assert r.status_code == 200
    # The hidden order-data form contains every field payment.js reads via FormData
    for needle in (
        'name="os" value="alpine-3.21"',
        'name="size" value="md"',
        'name="duration_days" value="14"',
        'name="ssh_pubkey" value="ssh-ed25519 KEY_HERE"',
        'name="hostname" value="myhost"',
        'name="domain_mode" value="auto"',
    ):
        assert needle in r.text, f"Missing hidden field: {needle}"


# --- /api proxy forwards to /v1/payments/networks ---


def test_proxy_forwards_payments_networks(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    payload = {
        "networks": [
            {
                "key": "base",
                "display_name": "Base",
                "caip2": "eip155:8453",
                "chain_id": 8453,
                "asset": "USDC",
                "token_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "token_decimals": 6,
                "eip712_domain": {"name": "USD Coin", "version": "2"},
                "rpc_url": "https://mainnet.base.org",
                "block_explorer_url": "https://basescan.org",
                "testnet": False,
            },
        ],
        "receiver_address": "0xabc",
        "facilitator_url": "https://x402.org/facilitator",
    }
    mocked_api.get("/v1/payments/networks").mock(return_value=httpx.Response(200, json=payload))
    r = client.get("/api/v1/payments/networks")
    assert r.status_code == 200
    body = r.json()
    assert body["networks"][0]["caip2"] == "eip155:8453"
    assert body["receiver_address"] == "0xabc"


def test_proxy_strips_v1_prefix_for_payments_networks(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The proxy accepts /api/payments/networks too (v1/ prefix is optional)."""
    route = mocked_api.get("/v1/payments/networks").mock(
        return_value=httpx.Response(200, json={"networks": []})
    )
    r = client.get("/api/payments/networks")
    assert r.status_code == 200
    assert route.called
