"""Direct unit tests for the _fetch_api helper.

Page-level tests (test_pages.py) already exercise it through the route layer,
but covering its success and failure branches directly keeps
the helper's contract testable in isolation if the page surface changes.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from hyrule_web.app import _fetch_api, app
from hyrule_web.config import settings


class _FakeRequest:
    """Minimal stand-in: _fetch_api only touches request.app.state.http."""

    def __init__(self, app_):
        self.app = app_


@pytest.fixture
def request_with_http():
    """An app with a real httpx.AsyncClient attached, for direct _fetch_api calls."""
    client = httpx.AsyncClient(base_url=settings.api_base_url, timeout=5)
    app.state.http = client
    yield _FakeRequest(app)
    # AsyncClient doesn't need explicit close for these tests; lifespan will
    # rebind app.state.http next time TestClient runs.


async def test_fetch_api_returns_json_on_200(request_with_http) -> None:
    with respx.mock(base_url=settings.api_base_url, assert_all_called=True) as rx:
        rx.get("/v1/things").mock(return_value=httpx.Response(200, json={"a": 1}))
        result = await _fetch_api(request_with_http, "/v1/things")
    assert result == {"a": 1}


async def test_fetch_api_returns_none_on_non_200(request_with_http) -> None:
    with respx.mock(base_url=settings.api_base_url, assert_all_called=True) as rx:
        rx.get("/v1/missing").mock(return_value=httpx.Response(404))
        result = await _fetch_api(request_with_http, "/v1/missing")
    assert result is None


async def test_fetch_api_returns_none_on_http_error(request_with_http) -> None:
    with respx.mock(base_url=settings.api_base_url, assert_all_called=True) as rx:
        rx.get("/v1/boom").mock(side_effect=httpx.ConnectError("nope"))
        result = await _fetch_api(request_with_http, "/v1/boom")
    assert result is None


@pytest.mark.parametrize(
    ("response", "path"),
    [
        (httpx.Response(200, json=[{"a": 1}]), "/v1/list"),
        (httpx.Response(200, text="not json"), "/v1/invalid-json"),
    ],
)
async def test_fetch_api_rejects_non_object_json(request_with_http, response, path) -> None:
    with respx.mock(base_url=settings.api_base_url, assert_all_called=True) as rx:
        rx.get(path).mock(return_value=response)
        result = await _fetch_api(request_with_http, path)
    assert result is None
