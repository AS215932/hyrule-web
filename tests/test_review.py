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


@pytest.mark.parametrize("size", list(VM_TIERS))
def test_review_renders_for_every_tier(client: TestClient, size: str) -> None:
    r = _post_review(client, size=size)
    assert r.status_code == 200
    expected_total = VM_TIERS[size]["price"] * 30
    assert f"{expected_total:.2f}" in r.text


def test_review_unknown_size_falls_back_to_sm(client: TestClient) -> None:
    r = _post_review(client, size="not-a-real-tier")
    assert r.status_code == 200
    # Page should render the Basic (sm) tier price for the fallback.
    expected_total = VM_TIERS["sm"]["price"] * 30
    assert f"{expected_total:.2f}" in r.text


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
