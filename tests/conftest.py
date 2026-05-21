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

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from hyrule_web.app import _NETWORK_CACHE, _RUNTIME_CACHE, app
from hyrule_web.config import settings


@pytest.fixture
def mocked_api() -> Iterator[respx.MockRouter]:
    """Intercept every hyrule-cloud API call. Tests register their own routes."""
    with respx.mock(base_url=settings.api_base_url, assert_all_called=False) as rx:
        rx.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
            "api_p50_ms": 24,
            "api_p50_source": "api-process-local-rolling-window",
            "api_p50_sample_count": 100,
            "build_queue": 0,
            "live_vms": 5,
            "avg_provision_seconds": 60,
            "updated_at": "2026-05-19T00:00:00+00:00",
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
            "receiver_address": "",
            "facilitator_url": "https://x402.org/facilitator",
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
    _NETWORK_CACHE["value"] = None
    _NETWORK_CACHE["expires_at"] = 0.0
    with TestClient(app) as c:
        yield c
