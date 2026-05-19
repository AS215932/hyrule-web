"""Block C (Wave 3) — chain selector in review.html.

Verifies that the review page wires the dispatcher correctly: chain
selector + hidden order form + payment-evm.js script tag. The actual JS
behaviour (fetch /api/payments/networks → render options → route to EVM
adapter) is tested in tests/test_proxy.py (the /api proxy) and the
backend's tests/test_payments_networks.py (wire shape).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _review_post_payload() -> dict:
    return {
        "os": "debian-13",
        "size": "sm",
        "duration": 30,
        "ssh_pubkey": "ssh-ed25519 AAAA",
        "hostname": "test-host",
        "domain_mode": "auto",
    }


def test_review_renders_chain_selector_and_dispatcher(client: TestClient) -> None:
    """Block C: the review page must render the <select id="payment-chain">
    plus the dispatcher + EVM adapter script tags. JS populates the options
    at runtime; the template only provides the structure."""
    r = client.post("/order/review", data=_review_post_payload())
    assert r.status_code == 200
    body = r.text
    assert 'id="payment-chain"' in body
    assert 'id="payment-chain-wrap"' in body
    assert 'id="order-data"' in body
    assert 'id="pay-btn"' in body
    assert "/static/payment-evm.js" in body
    assert "/static/payment.js" in body


def test_review_does_not_hardcode_chain_in_html(client: TestClient) -> None:
    """Block C: per [[feedback_verified_payment_chains]] the chain list MUST
    come from /v1/payments/networks at runtime — not from a hardcoded
    {% for %} loop in the template. The placeholder option is the only
    pre-populated entry."""
    r = client.post("/order/review", data=_review_post_payload())
    body = r.text
    # The only <option> in the rendered template before JS runs is the
    # "Loading chains…" placeholder.
    option_count = body.count("<option")
    assert option_count == 1, f"expected 1 placeholder option, found {option_count}"
    assert "Loading chains" in body


def test_review_order_data_form_carries_all_fields(client: TestClient) -> None:
    """The hidden order-data form must carry every field the JS dispatcher
    posts to /api/vm/create. Missing one (e.g. ssh_pubkey) would silently
    submit an invalid order on the next deploy."""
    r = client.post("/order/review", data=_review_post_payload())
    body = r.text
    for field in (
        'name="os"', 'name="size"', 'name="duration_days"',
        'name="ssh_pubkey"', 'name="hostname"', 'name="domain_mode"',
        'name="domain"',
    ):
        assert field in body, f"missing hidden field {field}"
