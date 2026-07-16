from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from hyrule_web.app import (
    _CATALOG_CACHE,
    _RUNTIME_CACHE,
    _SERVICE_STATUS_CACHE,
    _TOOL_CATALOG_CACHE,
    app,
)
from hyrule_web.config import settings


def _ready_capabilities() -> dict[str, object]:
    return {
        "service": "nat",
        "purpose": "Network observations",
        "separation_of_concerns": "Observers and enrichments are separate.",
        "free_endpoints": [
            {
                "path": "/v1/ip-check/sessions",
                "method": "POST",
                "description": "Create a probe manifest",
                "paid": False,
            }
        ],
        "paid_endpoints": [],
    }


@asynccontextmanager
async def _web_client() -> AsyncIterator[AsyncClient]:
    for cache in (_CATALOG_CACHE, _RUNTIME_CACHE, _SERVICE_STATUS_CACHE, _TOOL_CATALOG_CACHE):
        cache["value"] = None
        cache["expires_at"] = 0.0
    _SERVICE_STATUS_CACHE["successful_at"] = 0.0
    _TOOL_CATALOG_CACHE["successful_at"] = 0.0
    had_client = hasattr(app.state, "http")
    old_client = getattr(app.state, "http", None)
    backend = AsyncClient(base_url=settings.api_base_url, timeout=30)
    app.state.http = backend
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await backend.aclose()
        if had_client:
            app.state.http = old_client
        else:
            delattr(app.state, "http")


@pytest.mark.asyncio
async def test_ip_check_is_dark_in_routes_navigation_sitemap_and_llms(
    mocked_api: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_ip_check", False)
    async with _web_client() as client:
        assert (await client.get("/ip-check")).status_code == 404
        assert 'href="/ip-check"' not in (await client.get("/")).text
        assert "https://hyrule.host/ip-check" not in (await client.get("/sitemap.xml")).text
        assert "Agent-first network environment check" not in (await client.get("/llms.txt")).text


@pytest.mark.asyncio
async def test_ip_check_requires_live_backend_capability(
    mocked_api: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_ip_check", True)
    mocked_api.get("/v1/nat/capabilities").mock(
        return_value=httpx.Response(200, json={"free_endpoints": []})
    )
    async with _web_client() as client:
        assert (await client.get("/ip-check")).status_code == 404


@pytest.mark.asyncio
async def test_ip_check_renders_agent_first_browser_adapter_when_canaries_are_live(
    mocked_api: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_ip_check", True)
    mocked_api.get("/v1/nat/capabilities").mock(
        return_value=httpx.Response(200, json=_ready_capabilities())
    )
    async with _web_client() as client:
        response = await client.get("/ip-check")
        assert response.status_code == 200
        assert "No browser required" in response.text
        assert "browser probe adapter" in response.text
        assert "high-entropy browser traits" in response.text
        assert "Licensed providers are not enabled" in response.text
        assert 'type="module"' in response.text
        assert 'href="/ip-check"' in (await client.get("/")).text
        assert "https://hyrule.host/ip-check" in (await client.get("/sitemap.xml")).text
        assert "Agent-first network environment check" in (await client.get("/llms.txt")).text


@pytest.mark.asyncio
async def test_ip_check_hands_live_quality_operation_to_toolbox(
    mocked_api: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_ip_check", True)
    mocked_api.get("/v1/nat/capabilities").mock(
        return_value=httpx.Response(200, json=_ready_capabilities())
    )
    _TOOL_CATALOG_CACHE.update(value=None, expires_at=0.0, successful_at=0.0)
    mocked_api.get("/openapi.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "openapi": "3.1.0",
                "info": {"title": "Hyrule", "version": "1"},
                "paths": {
                    "/v1/ip/quality": {
                        "post": {
                            "operationId": "ip_quality_v1_ip_quality_post",
                            "summary": "IP quality",
                            "tags": ["IP intelligence"],
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"address": {"type": "string"}},
                                            "required": ["address"],
                                        },
                                        "example": {"address": "8.8.8.8"},
                                    }
                                }
                            },
                            "responses": {"200": {"description": "ok"}},
                            "x-payment-info": {
                                "price": {
                                    "mode": "fixed",
                                    "currency": "USD",
                                    "amount": "0.02",
                                }
                            },
                        }
                    }
                },
            },
        )
    )
    async with _web_client() as client:
        response = await client.get("/ip-check")
        assert response.status_code == 200
        assert 'id="ip-check-quality"' in response.text
        assert "Open paid report · $0.02" in response.text
        assert '"quality_tool_id": "ip_quality_v1_ip_quality_post"' in response.text


@pytest.mark.asyncio
async def test_browser_fingerprint_proxy_forwards_only_observable_browser_headers(
    mocked_api: respx.MockRouter,
) -> None:
    captured: list[httpx.Request] = []

    def fingerprint_response(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"fingerprint_id": "bf_test"})

    mocked_api.post("/v1/ip-check/sessions/ipc_test/fingerprints/browser").mock(
        side_effect=fingerprint_response
    )
    async with _web_client() as client:
        response = await client.post(
            "/api/ip-check/sessions/ipc_test/fingerprints/browser",
            json={"timezone": "Europe/Amsterdam"},
            headers={
                "User-Agent": "Browser Under Test/1.0",
                "Accept-Language": "nl-NL,nl;q=0.9",
                "Sec-CH-UA": '"Browser";v="1"',
                "Sec-CH-UA-Platform": '"Linux"',
                "X-Real-IP": "203.0.113.10",
            },
        )

    assert response.status_code == 200
    assert len(captured) == 1
    forwarded = captured[0].headers
    assert forwarded["user-agent"] == "Browser Under Test/1.0"
    assert forwarded["accept-language"] == "nl-NL,nl;q=0.9"
    assert forwarded["sec-ch-ua"] == '"Browser";v="1"'
    assert forwarded["sec-ch-ua-platform"] == '"Linux"'
    assert "x-real-ip" not in forwarded
