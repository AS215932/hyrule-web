"""Intent-led public tool pages and their machine-readable discovery surface."""

from __future__ import annotations

import json
import re
from html import unescape

from fastapi.testclient import TestClient

from hyrule_web.app import _tool_page_entry
from hyrule_web.tool_pages import TOOL_PAGES, TOOL_PAGES_BY_SLUG


def _json_ld(html: str) -> list[dict]:
    documents = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        flags=re.DOTALL,
    )
    return [json.loads(document) for document in documents]


def test_tool_page_metadata_and_relationships_are_unique() -> None:
    assert len(TOOL_PAGES) >= 10
    assert len(TOOL_PAGES_BY_SLUG) == len(TOOL_PAGES)
    assert len({page.title for page in TOOL_PAGES}) == len(TOOL_PAGES)
    assert len({page.meta_description for page in TOOL_PAGES}) == len(TOOL_PAGES)
    assert len({page.capability_id for page in TOOL_PAGES}) == len(TOOL_PAGES)
    assert len({page.path for page in TOOL_PAGES}) == len(TOOL_PAGES)
    for page in TOOL_PAGES:
        assert 40 <= len(page.meta_description) <= 180
        assert page.questions and page.evidence and page.workflow
        assert all(slug in TOOL_PAGES_BY_SLUG for slug in page.related)
        assert page.slug not in page.related


def test_tools_index_exposes_every_intent_page_and_collection_schema(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    assert "Start with the question, then choose the API" in response.text
    for page in TOOL_PAGES:
        assert f'href="{page.url}"' in response.text
        assert page.capability_id in response.text

    schemas = _json_ld(response.text)
    collection = next(document for document in schemas if document.get("@type") == "CollectionPage")
    assert len(collection["mainEntity"]["itemListElement"]) == len(TOOL_PAGES)


def test_each_tool_page_has_unique_copy_contract_and_structured_data(client: TestClient) -> None:
    for page in TOOL_PAGES:
        response = client.get(page.url)
        readable = unescape(response.text)
        assert response.status_code == 200, page.slug
        assert f"<title>{page.title}</title>" in response.text
        assert page.meta_description in readable
        assert f'<link rel="canonical" href="{page.absolute_url}">' in response.text
        assert page.headline in readable
        assert page.summary in readable
        assert page.capability_id in response.text
        assert f"{page.method} {page.path}" in response.text
        schemas = _json_ld(response.text)
        detail = next(
            document
            for document in schemas
            if "@graph" in document and len(document["@graph"]) == 3
        )
        service = next(item for item in detail["@graph"] if item.get("@type") == "Service")
        assert service["url"] == page.absolute_url
        assert service["subjectOf"] == "https://cloud.hyrule.host/openapi.json"


def test_sitemap_and_llms_include_every_intent_page(client: TestClient) -> None:
    sitemap = client.get("/sitemap.xml").text
    llms = client.get("/llms.txt").text
    for page in TOOL_PAGES:
        assert page.absolute_url in sitemap
        assert page.absolute_url in llms
        assert page.capability_id in llms


def test_unknown_tool_slug_is_404(client: TestClient) -> None:
    assert client.get("/tools/not-a-real-capability").status_code == 404


def test_live_tool_page_requires_exact_capability_id_and_manifest_entry() -> None:
    page = next(item for item in TOOL_PAGES if item.capability_id == "hyrule.dns.lookup")
    tool = {
        "method": page.method,
        "path": page.path,
        "capability_id": "hyrule.dns.changed",
        "price_display": "$0.001",
    }
    manifest_resource = {
        "id": page.capability_id,
        "method": page.method,
        "path": page.path,
    }

    wrong_id = _tool_page_entry(
        page,
        {"status": "live", "tools": [tool], "manifest_resources": [manifest_resource]},
    )
    assert wrong_id["live"] is False
    assert wrong_id["price_display"] is None

    tool["capability_id"] = page.capability_id
    missing_manifest = _tool_page_entry(
        page, {"status": "live", "tools": [tool], "manifest_resources": []}
    )
    assert missing_manifest["live"] is False

    confirmed = _tool_page_entry(
        page,
        {"status": "live", "tools": [tool], "manifest_resources": [manifest_resource]},
    )
    assert confirmed["live"] is True
    assert confirmed["price_display"] == "$0.001"
