"""Agent discovery at the brand origin (first live dogfood run).

hyrule.host is the origin agents find first, but every machine-readable
contract is authored on cloud.hyrule.host. Two defects were observed live:

- `GET https://hyrule.host/.well-known/x402.json` answered 404 while
  cloud.hyrule.host served the manifest — and llms.txt pointed at that path
  relatively, so a conforming agent dead-ended at discovery;
- `GET https://hyrule.host/openapi.json` answered 200 with `info.title`
  "Hyrule Cloud" and the website's HTML page routes as its paths — an OpenAPI
  document describing web pages instead of payable x402 resources.

Both URIs must now redirect to the canonical API host, and this app must never
publish a schema of its own.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.app import app
from hyrule_web.seo import CLOUD_OPENAPI_URL, CLOUD_X402_MANIFEST_URL


def test_well_known_x402_redirects_to_the_canonical_manifest(client: TestClient) -> None:
    r = client.get("/.well-known/x402.json", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == CLOUD_X402_MANIFEST_URL
    assert r.headers["location"] == "https://cloud.hyrule.host/.well-known/x402.json"


def test_openapi_json_redirects_to_the_canonical_document(client: TestClient) -> None:
    r = client.get("/openapi.json", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == CLOUD_OPENAPI_URL
    assert r.headers["location"] == "https://cloud.hyrule.host/openapi.json"


def test_app_publishes_no_self_authored_openapi_document(client: TestClient) -> None:
    """The website's page routes are not an API surface. A generated schema
    here was titled "Hyrule Cloud" — indistinguishable from the real agent
    API — and listed `/`, `/services`, `/order`… as its paths."""
    assert app.openapi_url is None
    r = client.get("/openapi.json", follow_redirects=False)
    assert r.status_code == 302
    # Nothing schema-shaped is served from this origin any more.
    for leak in ("openapi", "paths", "Hyrule Cloud", "/services", "/order"):
        assert leak not in r.text


def test_interactive_api_docs_are_not_exposed(client: TestClient) -> None:
    assert app.docs_url is None
    assert app.redoc_url is None
    assert client.get("/docs", follow_redirects=False).status_code == 404
    assert client.get("/redoc", follow_redirects=False).status_code == 404


def test_machine_discovery_uris_stay_out_of_the_sitemap(client: TestClient) -> None:
    """They are redirects for agents resolving a well-known path, not pages."""
    body = client.get("/sitemap.xml").text
    assert "https://hyrule.host/openapi.json" not in body
    assert "https://hyrule.host/.well-known/x402.json" not in body


def test_discovery_redirects_do_not_need_the_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Discovery is the one hop that has to work before an agent can do
    anything else, so it must not depend on a backend fetch."""
    mocked_api.get("/v1/status").mock(side_effect=httpx.ConnectError("backend down"))
    mocked_api.get("/openapi.json").mock(side_effect=httpx.ConnectError("backend down"))
    for path in ("/.well-known/x402.json", "/openapi.json"):
        assert client.get(path, follow_redirects=False).status_code == 302
