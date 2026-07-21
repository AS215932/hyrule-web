"""Shared pytest fixtures.

respx intercepts httpx at the transport layer, so the real FastAPI lifespan
runs unchanged (`app.state.http = httpx.AsyncClient(base_url=…)`) and tests
exercise the actual production transport stack — no DependencyOverride
gymnastics, no parallel mock infrastructure.

Block B (Wave 2): the base template now pulls `/v1/stats/runtime` into the
header pill on every page render. Pre-register a default mock here so any
page test that doesn't care about runtime values doesn't have to wire one
up. Per-test tests can still override by re-registering — respx uses the
most recently added matcher.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from hyrule_web.app import (
    _CATALOG_CACHE,
    _MAIL_PRICING_CACHE,
    _MAIL_PRODUCTS_CACHE,
    _PRICING_CACHE,
    _PRODUCTS_CACHE,
    _RUNTIME_CACHE,
    _SERVICE_STATUS_CACHE,
    _TOOL_CATALOG_CACHE,
    app,
)
from hyrule_web.config import VM_CUSTOMIZATION, VM_TIERS, settings


def _price_vm_payload(payload: dict) -> tuple[dict, dict, float]:
    """Mirror the API's cheapest-compatible-profile quote contract."""
    resources = payload.get("resources")
    if resources is None:
        selected = VM_TIERS[payload["size"]]
        resources = {
            "vcpu": selected["vcpu"],
            "ram_mb": selected["ram_mb"],
            "disk_gb": selected["disk_gb"],
        }
    cpu_rate = float(VM_CUSTOMIZATION["addon_prices"]["vcpu_usd_day"])
    ram_rate = float(VM_CUSTOMIZATION["addon_prices"]["ram_gb_usd_day"])
    disk_rate = float(VM_CUSTOMIZATION["addon_prices"]["disk_10gb_usd_day"])
    candidates: list[tuple[tuple[float, int, int, int], str, dict, tuple[int, int, int]]] = []
    for position, (profile, tier) in enumerate(VM_TIERS.items()):
        if any(tier[key] > resources[key] for key in ("vcpu", "ram_mb", "disk_gb")):
            continue
        addons = (
            resources["vcpu"] - tier["vcpu"],
            resources["ram_mb"] - tier["ram_mb"],
            resources["disk_gb"] - tier["disk_gb"],
        )
        daily = (
            tier["price"]
            + addons[0] * cpu_rate
            + addons[1] / 1024 * ram_rate
            + addons[2] / 10 * disk_rate
        )
        daily = round(daily, 2)
        candidates.append(
            (
                (
                    daily,
                    int(any(addons)),
                    addons[0] + addons[1] // 1024 + addons[2] // 10,
                    position,
                ),
                profile,
                tier,
                addons,
            )
        )
    sort_key, profile, tier, addons = min(candidates, key=lambda candidate: candidate[0])
    daily = sort_key[0]
    duration = payload["duration_days"]
    canonical_payload = {**payload, "size": profile, "resources": resources}
    pricing = {
        "base_profile": profile,
        "base_label": tier["name"],
        "base_price_usd_day": f"{tier['price']:.2f}",
        "addon_vcpu": addons[0],
        "addon_ram_mb": addons[1],
        "addon_disk_gb": addons[2],
        "addon_vcpu_usd_day": f"{addons[0] * cpu_rate:.2f}",
        "addon_ram_usd_day": f"{addons[1] / 1024 * ram_rate:.2f}",
        "addon_disk_usd_day": f"{addons[2] / 10 * disk_rate:.2f}",
        "daily_price_usd": f"{daily:.2f}",
        "duration_days": duration,
        "total_usd": f"{daily * duration:.2f}",
    }
    return canonical_payload, pricing, daily


@pytest.fixture
def mocked_api() -> Iterator[respx.MockRouter]:
    """Intercept every hyrule-cloud API call. Tests register their own routes."""
    with respx.mock(base_url=settings.api_base_url, assert_all_called=False) as rx:
        quotes: dict[str, dict] = {}

        def create_quote(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode())["order_payload"]
            quote_id = f"q_test_{len(quotes) + 1}"
            payload, pricing, daily = _price_vm_payload(payload)
            amount_usd = daily * payload["duration_days"]
            quote = {
                "quote_id": quote_id,
                "status": "created",
                "amount_usd": f"{amount_usd:.2f}",
                "expires_at": "2026-07-11T13:00:00+00:00",
                "order_payload": payload,
                "resources": payload["resources"],
                "pricing": pricing,
                "accepted_payment_methods": {
                    "evm": [
                        {"key": "base", "caip2": "eip155:8453", "asset": "USDC"},
                        {"key": "polygon", "caip2": "eip155:137", "asset": "USDC"},
                    ],
                    "native": [],
                },
            }
            quotes[quote_id] = quote
            rx.get(f"/v1/vm/quote/{quote_id}").mock(return_value=httpx.Response(200, json=quote))
            return httpx.Response(201, json=quote)

        rx.post("/v1/vm/quote", name="vm_quote").mock(side_effect=create_quote)
        rx.get("/v1/stats/runtime").mock(
            return_value=httpx.Response(
                200,
                json={
                    "api_p50_ms": 24,
                    "api_p50_source": "api-process-local-rolling-window",
                    "api_p50_sample_count": 100,
                    "build_queue": 0,
                    "live_vms": 5,
                    "avg_provision_seconds": 60,
                    "updated_at": "2026-05-19T00:00:00+00:00",
                },
            )
        )
        rx.get("/v1/status").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "operational",
                    "checked_at": "2026-07-11T12:00:00+00:00",
                    "stale": False,
                    "components": [
                        {
                            "id": "api_checkout",
                            "name": "API & checkout",
                            "status": "operational",
                            "message": "Purchasing and management API",
                        },
                        {
                            "id": "compute",
                            "name": "Compute",
                            "status": "operational",
                            "message": "VM provisioning and reachability",
                        },
                        {
                            "id": "intelligence",
                            "name": "Network intelligence",
                            "status": "operational",
                            "message": "Network diagnostics endpoints",
                        },
                        {
                            "id": "domains_dns",
                            "name": "Domains & DNS",
                            "status": "operational",
                            "message": "Registration and authoritative DNS",
                        },
                        {
                            "id": "network_proxy",
                            "name": "Network proxy",
                            "status": "operational",
                            "message": "Direct, Tor, I2P, and Yggdrasil egress",
                        },
                    ],
                    "incidents": [],
                },
            )
        )
        rx.get("/v1/os/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "templates": [
                        {
                            "name": "debian-13",
                            "description": "Debian 13 (Trixie)",
                            "default": True,
                            "family": "debian",
                        },
                    ],
                },
            )
        )
        # Block C (Wave 3): default payment networks so /faq, /llms.txt and the
        # review page render without each test re-wiring them. Override as needed.
        rx.get("/v1/payments/networks").mock(
            return_value=httpx.Response(
                200,
                json={
                    "networks": [
                        {
                            "key": "base",
                            "display_name": "Base",
                            "caip2": "eip155:8453",
                            "family": "evm",
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
                    "native": [],
                    "receiver_address": "",
                    "facilitator_url": "https://x402.org/facilitator",
                },
            )
        )
        rx.get("/v1/domains").mock(return_value=httpx.Response(200, json={"domains": []}))
        rx.get("/v1/mail/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "available": False,
                    "terms_version": "2026-08-04",
                    "backend": "dedicated Stalwart",
                    "products": [
                        {
                            "id": "agent-mail-hosted",
                            "title": "Agent mailbox on @agentmail.hyrule.host",
                            "price_usd": "1.00",
                            "billing": "30 days, no auto-renew",
                            "available": False,
                            "constraints": ["API-only submission and retrieval"],
                        }
                    ],
                },
            )
        )
        rx.get("/v1/mail/pricing").mock(
            return_value=httpx.Response(
                200,
                json={
                    "activation_usd": "1.00",
                    "outbound_message_usd": "0.01",
                    "inbound_usd": "0.00",
                    "storage_gb": 1,
                    "active_days": 30,
                    "grace_days": 7,
                    "auto_renew": False,
                },
            )
        )
        rx.get("/v1/auth/wallet").mock(
            return_value=httpx.Response(
                200, json={"address": None, "chain_id": None, "linked_at": None}
            )
        )
        rx.get("/v1/domains/tlds").mock(
            return_value=httpx.Response(
                200,
                json={
                    "refreshed_at": "2026-07-15T10:00:00+00:00",
                    "tlds": [
                        {
                            "tld": "dev",
                            "registration": {
                                "provider_cost_usd": "10.00",
                                "hyrule_fee_usd": "3.00",
                                "tax_usd": "0.00",
                                "total_usd": "13.00",
                                "currency": "USD",
                            },
                            "renewal": {
                                "provider_cost_usd": "12.00",
                                "hyrule_fee_usd": "3.00",
                                "tax_usd": "0.00",
                                "total_usd": "15.00",
                                "currency": "USD",
                            },
                            "refreshed_at": "2026-07-15T10:00:00+00:00",
                        }
                    ],
                },
            )
        )
        # Overhaul: live VM product catalog for the tier grids (index/services/
        # order). Mirrors the real GET /v1/products/vms response.
        rx.get("/v1/products/vms").mock(
            return_value=httpx.Response(
                200,
                json={
                    "currency": "USD",
                    "billing": "prepaid-daily",
                    "products": [
                        {
                            "size": "xs",
                            "name": "1C-1G-10G",
                            "vcpu": 1,
                            "ram_mb": 1024,
                            "disk_gb": 10,
                            "price_usd_day": "0.20",
                        },
                        {
                            "size": "sm",
                            "name": "1C-2G-20G",
                            "vcpu": 1,
                            "ram_mb": 2048,
                            "disk_gb": 20,
                            "price_usd_day": "0.40",
                        },
                        {
                            "size": "md",
                            "name": "2C-4G-20G",
                            "vcpu": 2,
                            "ram_mb": 4096,
                            "disk_gb": 20,
                            "price_usd_day": "0.60",
                        },
                        {
                            "size": "lg",
                            "name": "4C-4G-40G",
                            "vcpu": 4,
                            "ram_mb": 4096,
                            "disk_gb": 40,
                            "price_usd_day": "0.80",
                        },
                    ],
                    "customization": VM_CUSTOMIZATION,
                },
            )
        )
        # Legacy manifest fixture plus live proxy-route pricing. Public operation
        # discovery now comes from the enabled-only OpenAPI fixture below.
        rx.get("/.well-known/x402.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "Hyrule Cloud",
                    "resources": [
                        {
                            "path": "/v1/vm/create",
                            "method": "POST",
                            "description": "Provision a bare VM with SSH access",
                            "minPrice": "0.20",
                        },
                        {
                            "path": "/v1/domains/orders",
                            "method": "POST",
                            "description": "Place a domain registration or renewal",
                            "minPrice": "6.00",
                        },
                        {
                            "path": "/v1/network/request",
                            "method": "POST",
                            "description": "Proxied network request",
                            "minPrice": "0.01",
                        },
                        {
                            "path": "/v1/dns/lookup",
                            "method": "POST",
                            "description": "Paid DNS lookup",
                            "minPrice": "0.001",
                        },
                        {
                            "path": "/v1/bgp/lookup",
                            "method": "POST",
                            "description": "Paid BGP lookup",
                            "minPrice": "0.005",
                        },
                        {
                            "path": "/v1/web/tls/deep",
                            "method": "POST",
                            "description": "Deep TLS scan",
                            "minPrice": "0.10",
                        },
                    ],
                },
            )
        )
        rx.get("/openapi.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "openapi": "3.1.0",
                    "info": {"title": "Hyrule enabled x402 API", "version": "test"},
                    "paths": {
                        "/v1/vm/create": {
                            "post": {
                                "operationId": "create_vm",
                                "summary": "Provision a bare VM",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {"quote_id": {"type": "string"}},
                                                "required": ["quote_id"],
                                            },
                                            "example": {"quote_id": "q_test"},
                                        }
                                    }
                                },
                                "responses": {
                                    "202": {
                                        "content": {
                                            "application/json": {"schema": {"type": "object"}}
                                        }
                                    }
                                },
                                "x-payment-info": {
                                    "price": {"mode": "dynamic", "currency": "USD", "min": "0.20"}
                                },
                            }
                        },
                        "/v1/network/request": {
                            "post": {
                                "operationId": "network_request",
                                "summary": "Proxied network request",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {"type": "object"},
                                            "example": {"url": "https://example.com"},
                                        }
                                    }
                                },
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {"schema": {"type": "object"}}
                                        }
                                    }
                                },
                                "x-payment-info": {
                                    "price": {
                                        "mode": "dynamic",
                                        "currency": "USD",
                                        "min": "0.01",
                                        "max": "0.05",
                                    }
                                },
                            }
                        },
                        "/v1/dns/lookup": {
                            "post": {
                                "tags": ["DNS lookup"],
                                "operationId": "dns_lookup",
                                "summary": "Paid DNS lookup",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "$ref": "#/components/schemas/DNSLookupRequest"
                                            },
                                            "example": {"name": "example.com", "type": "AAAA"},
                                        }
                                    }
                                },
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {"schema": {"type": "object"}}
                                        }
                                    }
                                },
                                "x-payment-info": {
                                    "price": {"mode": "fixed", "currency": "USD", "amount": "0.001"}
                                },
                            }
                        },
                        "/v1/bgp/lookup": {
                            "post": {
                                "tags": ["BGP intelligence"],
                                "operationId": "bgp_lookup",
                                "summary": "Paid BGP lookup",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {"type": "object"},
                                            "example": {
                                                "subject": {"type": "asn", "value": "AS215932"}
                                            },
                                        }
                                    }
                                },
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {"schema": {"type": "object"}}
                                        }
                                    }
                                },
                                "x-payment-info": {
                                    "price": {"mode": "fixed", "currency": "USD", "amount": "0.005"}
                                },
                            }
                        },
                        "/v1/web/tls/deep": {
                            "post": {
                                "tags": ["Web reachability"],
                                "operationId": "web_tls_deep",
                                "summary": "Deep TLS scan",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {"type": "object"},
                                            "example": {"host": "example.com"},
                                        }
                                    }
                                },
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/json": {"schema": {"type": "object"}}
                                        }
                                    }
                                },
                                "x-payment-info": {
                                    "price": {"mode": "fixed", "currency": "USD", "amount": "0.10"}
                                },
                            }
                        },
                        "/v1/bgp/snapshots/router/{snapshot_id}/download": {
                            "get": {
                                "tags": ["BGP intelligence"],
                                "operationId": "bgp_snapshot_download",
                                "summary": "Download BGP snapshot",
                                "parameters": [
                                    {
                                        "name": "snapshot_id",
                                        "in": "path",
                                        "required": True,
                                        "schema": {"type": "string"},
                                        "example": "snap_test",
                                    }
                                ],
                                "responses": {
                                    "200": {
                                        "content": {
                                            "application/gzip": {
                                                "schema": {"type": "string", "format": "binary"}
                                            }
                                        }
                                    }
                                },
                                "x-payment-info": {
                                    "price": {"mode": "fixed", "currency": "USD", "amount": "0.10"}
                                },
                            }
                        },
                    },
                    "components": {
                        "schemas": {
                            "DNSLookupRequest": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "minLength": 1},
                                    "type": {"type": "string", "enum": ["A", "AAAA", "MX"]},
                                },
                                "required": ["name"],
                            }
                        }
                    },
                },
            )
        )
        rx.get("/v1/pricing").mock(
            return_value=httpx.Response(
                200,
                json={
                    "vm_prices": {"xs (1C-1G-10G)": "$0.20/day"},
                    "vm_customization": VM_CUSTOMIZATION,
                    "domain_auto": "$0.00 (subdomain under deploy.hyrule.host)",
                    "proxy_prices": {
                        "direct": "$0.01/request",
                        "tor": "$0.05/request",
                        "i2p": "$0.05/request",
                        "yggdrasil": "$0.03/request",
                    },
                    "currency": "USDC",
                    "network": "Base (eip155:8453)",
                },
            )
        )
        yield rx


@pytest.fixture
def client(mocked_api: respx.MockRouter) -> Iterator[TestClient]:
    """TestClient that drives the real lifespan; mocked_api intercepts the AsyncClient.

    Clears the in-process runtime cache (Block B) before each test so a cached
    value from a prior test doesn't shadow a tailored mock the current test
    sets up.
    """
    _RUNTIME_CACHE["value"] = None
    _RUNTIME_CACHE["expires_at"] = 0.0
    _SERVICE_STATUS_CACHE["value"] = None
    _SERVICE_STATUS_CACHE["expires_at"] = 0.0
    _SERVICE_STATUS_CACHE["successful_at"] = 0.0
    _CATALOG_CACHE["value"] = None
    _CATALOG_CACHE["expires_at"] = 0.0
    _PRODUCTS_CACHE["value"] = None
    _PRODUCTS_CACHE["expires_at"] = 0.0
    _TOOL_CATALOG_CACHE["value"] = None
    _TOOL_CATALOG_CACHE["expires_at"] = 0.0
    _TOOL_CATALOG_CACHE["successful_at"] = 0.0
    _PRICING_CACHE["value"] = None
    _PRICING_CACHE["expires_at"] = 0.0
    _MAIL_PRICING_CACHE["value"] = None
    _MAIL_PRICING_CACHE["expires_at"] = 0.0
    _MAIL_PRICING_CACHE["retry_at"] = 0.0
    _MAIL_PRODUCTS_CACHE["value"] = None
    _MAIL_PRODUCTS_CACHE["expires_at"] = 0.0
    _MAIL_PRODUCTS_CACHE["retry_at"] = 0.0
    with TestClient(app) as c:
        yield c
