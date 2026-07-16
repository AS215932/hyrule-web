"""Enabled-only OpenAPI normalization and fail-closed toolbox routes."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.app import _CATALOG_CACHE, _TOOL_CATALOG_CACHE
from hyrule_web.catalog import browser_catalog, catalog_resources, normalize_openapi


def test_normalize_openapi_resolves_schema_and_classifies_surfaces() -> None:
    document = {
        "info": {"title": "Paid", "version": "1"},
        "paths": {
            "/v1/dns/lookup": {
                "post": {
                    "tags": ["DNS lookup"],
                    "operationId": "dns_lookup",
                    "summary": "DNS lookup",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Lookup"},
                                "example": {"name": "example.com"},
                            }
                        }
                    },
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"type": "object"}}}}
                    },
                    "x-payment-info": {
                        "price": {"mode": "fixed", "currency": "USD", "amount": "0.001"}
                    },
                }
            },
            "/v1/vm/create": {
                "post": {
                    "operationId": "create_vm",
                    "summary": "Create VM",
                    "responses": {},
                    "x-payment-info": {
                        "price": {"mode": "dynamic", "currency": "USD", "min": "0.05"}
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Lookup": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            }
        },
    }
    result = normalize_openapi(document)
    tools = {tool["operation_id"]: tool for tool in result["tools"]}
    dns = tools["dns_lookup"]
    assert dns["executable"] is True
    assert dns["input_schema"]["properties"]["name"]["type"] == "string"
    assert dns["price_display"] == "$0.001"
    assert dns["description"] == "Inputs: name."
    assert dns["tool_code"] == "DNS"
    assert dns["catalog_blurb"].startswith("Resolve DNS records")
    assert "example.com" in dns["search_terms"]
    vm = tools["create_vm"]
    assert vm["executable"] is False
    assert vm["handoff_url"] == "/order"
    assert vm["tool_code"] == "VM"
    assert "dedicated order flow" in vm["catalog_blurb"]


def test_unknown_enabled_operation_gets_safe_catalog_copy() -> None:
    result = normalize_openapi(
        {
            "paths": {
                "/v1/future/check": {
                    "post": {
                        "tags": ["Future checks"],
                        "operationId": "future_check",
                        "summary": "Future check",
                        "responses": {},
                    }
                }
            }
        }
    )
    tool = result["tools"][0]
    assert tool["catalog_blurb"] == "Run Future check with a live x402 quote."
    assert tool["tool_code"] == "FUTURE CHECK"


def test_catalog_resources_suppresses_stale_prices() -> None:
    tool = {
        "path": "/v1/dns/lookup",
        "method": "POST",
        "description": "DNS",
        "min_price": "0.001",
        "price_display": "$0.001",
        "group": "intel",
    }
    live = catalog_resources({"status": "live", "tools": [tool]})[0]
    stale = catalog_resources({"status": "stale", "tools": [tool]})[0]
    assert live["min_price"] == "0.001"
    assert stale["min_price"] is None
    assert stale["price_display"] == "Unavailable"


def test_browser_catalog_drops_large_server_only_contracts() -> None:
    compact = browser_catalog(
        {
            "status": "live",
            "tools": [
                {
                    "operation_id": "dns_lookup",
                    "input_schema": {"type": "object"},
                    "output_schema": {"properties": {"large": {"type": "object"}}},
                    "price": {"mode": "fixed"},
                }
            ],
        }
    )
    assert compact["status"] == "live"
    assert compact["tools"] == [{"operation_id": "dns_lookup", "input_schema": {"type": "object"}}]


def test_toolbox_renders_enabled_openapi_and_webmcp_entry(client: TestClient) -> None:
    response = client.get("/toolbox")
    assert response.status_code == 200
    assert "Paid DNS lookup" in response.text
    assert "Resolve DNS records with resolver" in response.text
    assert 'id="toolbox-result-count"' in response.text
    assert "Runnable diagnostics" in response.text
    assert "Product handoffs" in response.text
    assert 'class="tool-drawer"' in response.text
    assert 'class="toolbox-grid"' not in response.text
    assert "dns_lookup" in response.text
    assert "toolbox-" in response.text
    assert 'type="module"' in response.text
    assert 'href="/toolbox"' in client.get("/").text
    assert "https://hyrule.host/toolbox" in client.get("/sitemap.xml").text


def test_toolbox_fails_closed_without_fresh_discovery(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/openapi.json").mock(side_effect=httpx.ConnectError("offline"))
    response = client.get("/toolbox")
    assert response.status_code == 200
    assert "No static endpoint list" in response.text
    assert "Paid DNS lookup" not in response.text


def test_empty_enabled_catalog_is_authoritative(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/openapi.json").mock(
        return_value=httpx.Response(
            200,
            json={"openapi": "3.1.0", "info": {"title": "Paid"}, "paths": {}},
        )
    )
    response = client.get("/toolbox")
    assert response.status_code == 200
    assert "Live enabled catalog" in response.text
    assert "No enabled operations can be confirmed right now" in response.text
    assert "Paid DNS lookup" not in response.text
    assert '"execution_enabled": false' in response.text


def test_toolbox_disables_execution_with_stale_payment_networks(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    _CATALOG_CACHE.update(
        value={
            "networks": [
                {
                    "key": "base",
                    "caip2": "eip155:8453",
                    "family": "evm",
                    "display_name": "Base",
                    "asset": "USDC",
                }
            ]
        },
        expires_at=0.0,
    )
    mocked_api.get("/v1/payments/networks").mock(side_effect=httpx.ConnectError("offline"))
    response = client.get("/toolbox")
    assert response.status_code == 200
    assert "payment-network discovery unavailable, so execution is paused" in response.text
    assert '"execution_enabled": false' in response.text


def test_services_labels_stale_operations_and_withholds_prices(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    assert client.get("/services").status_code == 200
    _TOOL_CATALOG_CACHE["expires_at"] = 0.0
    mocked_api.get("/openapi.json").mock(side_effect=httpx.ConnectError("offline"))
    response = client.get("/services")
    assert response.status_code == 200
    assert "Enabled-operation discovery is temporarily stale" in response.text
    assert "/v1/dns/lookup" in response.text
    assert "Unavailable" in response.text


def test_public_pages_never_expose_conventional_mcp_service(client: TestClient) -> None:
    for path in ("/", "/agents", "/toolbox", "/about", "/llms.txt"):
        text = client.get(path).text.lower()
        assert "hyrule-mcp" not in text
        assert "mcp server" not in text
        assert "mcp config" not in text
