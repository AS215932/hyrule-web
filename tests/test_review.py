"""POST /order/review — every tier, unknown-size fallback, optional fields."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hyrule_web.config import VM_TIERS


def _post_review(client: TestClient, **overrides: object) -> object:
    form = {
        "os": "debian-13",
        "size": "sm",
        "duration": "30",
        "ssh_pubkey": "ssh-ed25519 AAAA test",
    }
    form.update({k: str(v) for k, v in overrides.items()})
    return client.post("/order/review", data=form)


def test_native_form_creates_durable_quote_and_redirects(client: TestClient) -> None:
    form = {
        "os": "debian-13",
        "size": "sm",
        "duration": "30",
        "ssh_pubkey": "ssh-ed25519 AAAA test",
    }
    response = client.post("/order/review", data=form, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/order/review/q_test_")


@pytest.mark.parametrize("size", list(VM_TIERS))
def test_review_renders_for_every_tier(client: TestClient, size: str) -> None:
    r = _post_review(client, size=size)
    assert r.status_code == 200
    expected_total = VM_TIERS[size]["price"] * 30
    assert f"{expected_total:.2f}" in r.text


def test_review_unknown_size_is_rejected_without_creating_quote(client: TestClient) -> None:
    r = _post_review(client, size="not-a-real-tier")
    assert r.status_code == 422
    assert "Choose a valid server size." in r.text
    assert "Quote not created" in r.text


def test_review_duration_multiplies_price(client: TestClient) -> None:
    r = _post_review(client, size="md", duration="7")
    assert r.status_code == 200
    expected_total = VM_TIERS["md"]["price"] * 7
    assert f"{expected_total:.2f}" in r.text


def test_review_optional_fields_default_to_empty(client: TestClient) -> None:
    # Don't pass hostname/domain_mode/domain — they have Form() defaults.
    r = _post_review(client)
    assert r.status_code == 200


def test_review_with_custom_domain(client: TestClient) -> None:
    r = _post_review(
        client,
        hostname="my-vm",
        domain_mode="custom",
        domain="example.com",
    )
    assert r.status_code == 200
