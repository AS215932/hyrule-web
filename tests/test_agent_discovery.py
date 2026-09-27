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
import pytest
import respx
from fastapi.testclient import TestClient

import hyrule_web.app as webapp
from hyrule_web.app import _AGENT_CARD_CACHE, app
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


# --- agent-card mirror ---


def test_agent_card_is_mirrored_from_the_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Unlike x402.json this is a mirror, not a redirect: the card body is
    host-independent (its url fields point at cloud.hyrule.host)."""
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    card = r.json()
    assert card["name"] == "Hyrule Cloud"
    assert card["url"] == "https://cloud.hyrule.host"


def test_agent_card_fails_closed_when_backend_404s(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The cloud side ships in a parallel PR. Until it serves the card, this
    mirror must answer an explicit unavailable — never fabricate a card."""
    mocked_api.get("/.well-known/agent-card.json").mock(return_value=httpx.Response(404))
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 503
    assert "unavailable" in r.text


def test_agent_card_fails_closed_when_backend_unreachable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/.well-known/agent-card.json").mock(
        side_effect=httpx.ConnectError("backend down")
    )
    assert client.get("/.well-known/agent-card.json").status_code == 503


def test_agent_card_serves_stale_copy_when_backend_degrades(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """_refresh_cached semantics: one good fetch, then stale-on-error."""
    assert client.get("/.well-known/agent-card.json").status_code == 200
    mocked_api.get("/.well-known/agent-card.json").mock(
        side_effect=httpx.ConnectError("backend down")
    )
    _AGENT_CARD_CACHE["expires_at"] = 0.0  # force TTL expiry past 300s
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    assert r.json()["url"] == "https://cloud.hyrule.host"


# --- IndexNow key file ---


def test_indexnow_txt_is_404_while_no_key_is_configured(client: TestClient) -> None:
    """Same gate as hyrule-cloud's agent-seo-verification: never publish a
    placeholder key a search engine would then fail to validate."""
    assert client.get("/indexnow.txt").status_code == 404


def test_indexnow_txt_serves_the_configured_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webapp.settings, "indexnow_key", "0f8fad5bd9cb469fa165708be95c4ce6")
    r = client.get("/indexnow.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert r.text == "0f8fad5bd9cb469fa165708be95c4ce6"


def test_new_machine_paths_stay_out_of_the_sitemap(client: TestClient) -> None:
    body = client.get("/sitemap.xml").text
    assert "agent-card.json" not in body
    assert "indexnow.txt" not in body
