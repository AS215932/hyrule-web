"""SEO routes — /robots.txt, /sitemap.xml, /llms.txt."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from hyrule_web.seo import LLMS_TXT, ROBOTS_TXT


def test_robots_txt_route(client: TestClient) -> None:
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert r.text == ROBOTS_TXT


def test_llms_txt_route(client: TestClient) -> None:
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert r.text == LLMS_TXT


def test_sitemap_xml_route_is_valid_xml(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]
    root = ET.fromstring(r.text)
    assert root.tag.endswith("urlset")


def test_sitemap_xml_excludes_api_partials_and_dynamic_routes(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    assert "/api/" not in body
    assert "/partials/" not in body
    assert "/order/status/" not in body  # dynamic per-user
    assert "/order/review" not in body   # POST-only


def test_sitemap_xml_includes_known_public_paths(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    body = r.text
    for path in ("https://hyrule.host/", "https://hyrule.host/services",
                 "https://hyrule.host/order", "https://hyrule.host/llms.txt"):
        assert path in body
