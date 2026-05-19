"""Block B (Wave 2) — live runtime stats pill in base.html.

Verifies that:
  - homepage replaces the prior hardcoded `api · 24ms` with values from
    `/v1/stats/runtime`,
  - the 15s frontend cache short-circuits the second request,
  - a backend failure with no cached value falls back to `api · —` (no 500),
  - stale-on-error: once a good value is cached, a subsequent backend
    failure keeps serving the last good value rather than dropping to —.
"""

from __future__ import annotations

import time

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.app import _RUNTIME_CACHE, _RUNTIME_TTL_SECONDS


def test_runtime_pill_renders_p50_from_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    # The default mocked_api fixture already returns api_p50_ms=24.
    r = client.get("/")
    assert r.status_code == 200
    # Header pill carries the value with the new title text.
    assert "api · 24ms" in r.text
    assert "API p50 latency" in r.text


def test_runtime_pill_fallback_when_backend_down_and_no_cache(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block B: with no cached value, backend failure renders `api · —`
    rather than 500-ing or showing a misleading number."""
    # Override the default fixture: respx prefers the most recently added matcher.
    mocked_api.get("/v1/stats/runtime").mock(side_effect=httpx.ConnectError("down"))
    r = client.get("/")
    assert r.status_code == 200
    assert "api · —" in r.text


def test_runtime_pill_stale_on_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block B: once /v1/stats/runtime has cached a good value, a later
    backend failure keeps serving the stale value — better UX than flicker."""
    route = mocked_api.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
        "api_p50_ms": 42,
        "api_p50_source": "api-process-local-rolling-window",
        "api_p50_sample_count": 50,
        "build_queue": 1,
        "live_vms": 7,
        "avg_provision_seconds": 55,
        "updated_at": "2026-05-19T00:00:00+00:00",
    }))
    r1 = client.get("/")
    assert "api · 42ms" in r1.text

    # Force cache expiry so the next request actually re-fetches.
    _RUNTIME_CACHE["expires_at"] = 0.0
    # Backend now fails.
    route.mock(side_effect=httpx.ConnectError("transient"))
    r2 = client.get("/")
    # Stale value still served.
    assert "api · 42ms" in r2.text


def test_runtime_pill_cache_short_circuits_second_request(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block B: within the 15s TTL, repeated page renders should not hit
    the backend again. Holds backend load constant under traffic spikes."""
    route = mocked_api.get("/v1/stats/runtime").mock(return_value=httpx.Response(200, json={
        "api_p50_ms": 11,
        "api_p50_source": "api-process-local-rolling-window",
        "api_p50_sample_count": 1,
        "build_queue": 0,
        "live_vms": 1,
        "avg_provision_seconds": 60,
        "updated_at": "2026-05-19T00:00:00+00:00",
    }))
    client.get("/")
    client.get("/")
    client.get("/")
    assert route.call_count == 1
    # Sanity: the cache really is the gate (TTL is in the future).
    assert _RUNTIME_CACHE["expires_at"] > time.time()
    assert _RUNTIME_TTL_SECONDS == 15
