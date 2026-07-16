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
    _MANIFEST_CACHE,
    _NETWORK_CACHE,
    _PRICING_CACHE,
    _PRODUCTS_CACHE,
    _RUNTIME_CACHE,
    _SERVICE_STATUS_CACHE,
    app,
)
from hyrule_web.config import VM_TIERS, settings


@pytest.fixture
def mocked_api() -> Iterator[respx.MockRouter]:
    """Intercept every hyrule-cloud API call. Tests register their own routes."""
    with respx.mock(base_url=settings.api_base_url, assert_all_called=False) as rx:
        quotes: dict[str, dict] = {}

        def create_quote(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode())["order_payload"]
            quote_id = f"q_test_{len(quotes) + 1}"
            tier = VM_TIERS.get(payload["size"], {"price": 1.0})
            amount_usd = tier["price"] * payload["duration_days"]
            quote = {
                "quote_id": quote_id,
                "status": "active",
                "amount_usd": f"{amount_usd:.2f}",
                "expires_at": "2026-07-11T13:00:00+00:00",
                "order_payload": payload,
                "accepted_payment_methods": {
                    "evm": [
                        {"key": "base", "caip2": "eip155:8453", "asset": "USDC"},
                        {"key": "polygon", "caip2": "eip155:137", "asset": "USDC"},
                    ],
                    "native": [],
                },
            }
            quotes[quote_id] = quote
            rx.get(f"/v1/vm/quote/{quote_id}").mock(
                return_value=httpx.Response(200, json=quote)
            )
            return httpx.Response(201, json=quote)

        rx.post("/v1/vm/quote").mock(side_effect=create_quote)
        rx.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
            "api_p50_ms": 24,
            "api_p50_source": "api-process-local-rolling-window",
            "api_p50_sample_count": 100,
            "build_queue": 0,
            "live_vms": 5,
            "avg_provision_seconds": 60,
            "updated_at": "2026-05-19T00:00:00+00:00",
        }))
        rx.get("/v1/status").mock(return_value=httpx.Response(200, json={
            "status": "operational",
            "checked_at": "2026-07-11T12:00:00+00:00",
            "stale": False,
            "components": [
                {"id": "api_checkout", "name": "API & checkout", "status": "operational",
                 "message": "Purchasing and management API"},
                {"id": "compute", "name": "Compute", "status": "operational",
                 "message": "VM provisioning and reachability"},
                {"id": "intelligence", "name": "Network intelligence", "status": "operational",
                 "message": "Network diagnostics endpoints"},
                {"id": "domains_dns", "name": "Domains & DNS", "status": "operational",
                 "message": "Registration and authoritative DNS"},
                {"id": "network_proxy", "name": "Network proxy", "status": "operational",
                 "message": "Direct, Tor, I2P, and Yggdrasil egress"},
            ],
            "incidents": [],
        }))
        rx.get("/v1/os/list").mock(return_value=httpx.Response(200, json={
            "templates": [
                {"name": "debian-13", "description": "Debian 13 (Trixie)",
                 "default": True, "family": "debian"},
            ],
        }))
        # Block C (Wave 3): default payment networks so /faq, /llms.txt and the
        # review page render without each test re-wiring them. Override as needed.
        rx.get("/v1/payments/networks").mock(return_value=httpx.Response(200, json={
            "networks": [
                {"key": "base", "display_name": "Base", "caip2": "eip155:8453",
                 "family": "evm", "chain_id": 8453, "asset": "USDC",
                 "token_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                 "token_decimals": 6,
                 "eip712_domain": {"name": "USD Coin", "version": "2"},
                 "rpc_url": "https://mainnet.base.org",
                 "block_explorer_url": "https://basescan.org",
                 "testnet": False},
            ],
            "native": [],
            "receiver_address": "",
            "facilitator_url": "https://x402.org/facilitator",
        }))
        rx.get("/v1/domains").mock(
            return_value=httpx.Response(200, json={"domains": []})
        )
        rx.get("/v1/auth/wallet").mock(
            return_value=httpx.Response(
                200, json={"address": None, "chain_id": None, "linked_at": None}
            )
        )
        rx.get("/v1/domains/tlds").mock(return_value=httpx.Response(200, json={
            "refreshed_at": "2026-07-15T10:00:00+00:00",
            "tlds": [
                {
                    "tld": "dev",
                    "registration": {
                        "provider_cost_usd": "10.00", "hyrule_fee_usd": "3.00",
                        "tax_usd": "0.00", "total_usd": "13.00", "currency": "USD",
                    },
                    "renewal": {
                        "provider_cost_usd": "12.00", "hyrule_fee_usd": "3.00",
                        "tax_usd": "0.00", "total_usd": "15.00", "currency": "USD",
                    },
                    "refreshed_at": "2026-07-15T10:00:00+00:00",
                }
            ],
        }))
        # Block H (Wave 5/6): default fleet stats for /transparency.
        rx.get("/v1/stats/network").mock(return_value=httpx.Response(200, json={
            "bgp_peers_established": 4,
            "ipv6_prefixes_announced": 3,
            "nat64_sessions_active": 1284,
            "transit_providers": ["AS34872", "AS210233"],
            "_source": "prometheus-http://[2a0c:b641:b50:2::50]:9090",
            "updated_at": "2026-05-19T00:00:00+00:00",
        }))
        # Overhaul: live VM product catalog for the tier grids (index/services/
        # order). Mirrors the real GET /v1/products/vms response — xs is 1 GB.
        rx.get("/v1/products/vms").mock(return_value=httpx.Response(200, json={
            "currency": "USD",
            "billing": "prepaid-daily",
            "products": [
                {"size": "xs", "name": "Starter", "vcpu": 1, "ram_mb": 1024,
                 "disk_gb": 10, "price_usd_day": "0.05"},
                {"size": "sm", "name": "Basic", "vcpu": 1, "ram_mb": 1024,
                 "disk_gb": 20, "price_usd_day": "0.10"},
                {"size": "md", "name": "Standard", "vcpu": 2, "ram_mb": 2048,
                 "disk_gb": 40, "price_usd_day": "0.20"},
                {"size": "lg", "name": "Performance", "vcpu": 4, "ram_mb": 4096,
                 "disk_gb": 80, "price_usd_day": "0.40"},
            ],
        }))
        # Overhaul: published x402 manifest (per-endpoint prices for /services
        # + /agents) and /v1/pricing (proxy route prices for /services).
        rx.get("/.well-known/x402.json").mock(return_value=httpx.Response(200, json={
            "name": "Hyrule Cloud",
            "resources": [
                {"path": "/v1/vm/create", "method": "POST",
                 "description": "Provision a bare VM with SSH access", "minPrice": "0.05"},
                {"path": "/v1/domains/orders", "method": "POST",
                 "description": "Place a domain registration or renewal", "minPrice": "6.00"},
                {"path": "/v1/network/request", "method": "POST",
                 "description": "Proxied network request", "minPrice": "0.01"},
                {"path": "/v1/dns/lookup", "method": "POST",
                 "description": "Paid DNS lookup", "minPrice": "0.001"},
                {"path": "/v1/bgp/lookup", "method": "POST",
                 "description": "Paid BGP lookup", "minPrice": "0.005"},
                {"path": "/v1/web/tls/deep", "method": "POST",
                 "description": "Deep TLS scan", "minPrice": "0.10"},
            ],
        }))
        rx.get("/v1/pricing").mock(return_value=httpx.Response(200, json={
            "vm_prices": {"xs (1vCPU/1GB/10GB)": "$0.05/day"},
            "domain_auto": "$0.00 (subdomain under deploy.hyrule.host)",
            "proxy_prices": {"direct": "$0.01/request", "tor": "$0.05/request",
                             "i2p": "$0.05/request", "yggdrasil": "$0.03/request"},
            "currency": "USDC",
            "network": "Base (eip155:8453)",
        }))
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
    _NETWORK_CACHE["value"] = None
    _NETWORK_CACHE["expires_at"] = 0.0
    _CATALOG_CACHE["value"] = None
    _CATALOG_CACHE["expires_at"] = 0.0
    _PRODUCTS_CACHE["value"] = None
    _PRODUCTS_CACHE["expires_at"] = 0.0
    _MANIFEST_CACHE["value"] = None
    _MANIFEST_CACHE["expires_at"] = 0.0
    _PRICING_CACHE["value"] = None
    _PRICING_CACHE["expires_at"] = 0.0
    with TestClient(app) as c:
        yield c
