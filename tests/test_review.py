"""POST /order/review — every tier, unknown-size fallback, optional fields."""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx
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


def test_order_renders_technical_profiles_and_exact_resource_controls(
    client: TestClient,
) -> None:
    response = client.get("/order?size=lg")

    assert response.status_code == 200
    for label in ("1C-1G-10G", "1C-2G-20G", "2C-4G-20G", "4C-4G-40G"):
        assert label in response.text
    for field in ('name="vcpu"', 'name="ram_mb"', 'name="disk_gb"'):
        assert field in response.text
    assert 'name="size" value="lg"' in response.text
    assert "maximum 4C / 8G / 40G" in response.text


def test_order_falls_back_from_malformed_live_customization(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/products/vms").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {
                        "size": "xs",
                        "name": "1C-1G-10G",
                        "vcpu": 1,
                        "ram_mb": 1024,
                        "disk_gb": 10,
                        "price_usd_day": "0.20",
                    }
                ],
                "customization": {
                    "minimum": {"vcpu": 1, "ram_mb": 1024, "disk_gb": 10},
                    "maximum": {"vcpu": 4, "ram_mb": 8192, "disk_gb": 40},
                    "increments": {"vcpu": 0, "ram_mb": 1024, "disk_gb": 10},
                    "addon_prices": {
                        "vcpu_usd_day": "0.10",
                        "ram_gb_usd_day": "0.15",
                        "disk_10gb_usd_day": "0.05",
                    },
                },
            },
        )
    )

    response = client.get("/order")

    assert response.status_code == 200
    assert 'name="vcpu"' in response.text
    assert re.search(r'<option value="4"\s*>4 vCPU</option>', response.text)


def test_profile_submission_uses_its_exact_defaults(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    quote_route = mocked_api["vm_quote"]

    response = _post_review(client, size="lg")

    assert response.status_code == 200
    payload = json.loads(quote_route.calls.last.request.content)
    assert payload["order_payload"]["resources"] == {
        "vcpu": 4,
        "ram_mb": 4096,
        "disk_gb": 40,
    }


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


def test_review_accepts_valid_resources_from_live_product_catalog(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/products/vms").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {
                        "size": "lg",
                        "name": "4C-8G-40G",
                        "vcpu": 4,
                        "ram_mb": 8192,
                        "disk_gb": 40,
                        "price_usd_day": "1.40",
                    }
                ]
            },
        )
    )

    response = _post_review(client, size="lg")

    assert response.status_code == 200
    assert "8 GB RAM" in response.text


def test_review_quotes_custom_exact_resources(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    quote_route = mocked_api["vm_quote"]

    response = _post_review(client, size="xs", vcpu=3, ram_mb=5120, disk_gb=30)

    assert response.status_code == 200
    payload = json.loads(quote_route.calls.last.request.content)
    assert payload["order_payload"]["resources"] == {
        "vcpu": 3,
        "ram_mb": 5120,
        "disk_gb": 30,
    }
    assert "3 vCPU" in response.text
    assert "5 GB RAM" in response.text
    assert "30 GB SSD" in response.text
    assert "2C-4G-20G" in response.text
    assert "30 days" in response.text
    assert "$0.90/day" in response.text


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


@pytest.mark.parametrize(
    "domain",
    ("", "localhost", "-example.com", "example..com", "bad label.example"),
)
def test_review_rejects_invalid_custom_domain(client: TestClient, domain: str) -> None:
    response = _post_review(client, domain_mode="custom", domain=domain)

    assert response.status_code == 422
    assert "Enter a valid fully-qualified domain name." in response.text
