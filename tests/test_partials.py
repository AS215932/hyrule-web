"""HTMX partials — /partials/price covers size fallback, isdigit parse, and clamp."""

from __future__ import annotations

from fastapi.testclient import TestClient

from hyrule_web.config import VM_TIERS


def _post(client: TestClient, size: str, duration: str) -> object:
    return client.post("/partials/price", data={"size": size, "duration": duration})


def test_partial_price_basic(client: TestClient) -> None:
    r = _post(client, size="sm", duration="30")
    assert r.status_code == 200
    expected = VM_TIERS["sm"]["price"] * 30
    assert f"${expected:.2f}" in r.text


def test_partial_price_unknown_size_falls_back_to_sm(client: TestClient) -> None:
    r = _post(client, size="not-real", duration="10")
    expected = VM_TIERS["sm"]["price"] * 10
    assert f"${expected:.2f}" in r.text


def test_partial_price_invalid_duration_defaults_to_30(client: TestClient) -> None:
    r = _post(client, size="sm", duration="not-a-number")
    expected = VM_TIERS["sm"]["price"] * 30
    assert f"${expected:.2f}" in r.text
    assert "30 days" in r.text


def test_partial_price_clamps_high_duration_to_365(client: TestClient) -> None:
    r = _post(client, size="sm", duration="9999")
    expected = VM_TIERS["sm"]["price"] * 365
    assert f"${expected:.2f}" in r.text
    assert "365 days" in r.text


def test_partial_price_clamps_low_duration_to_1(client: TestClient) -> None:
    # The clamp is max(1, min(365, ...)); 0 should round up to 1.
    r = _post(client, size="sm", duration="0")
    # "0".isdigit() is True, so int(0)=0 → max(1, min(365, 0)) = 1.
    expected = VM_TIERS["sm"]["price"] * 1
    assert f"${expected:.2f}" in r.text
    assert "1 days" in r.text
