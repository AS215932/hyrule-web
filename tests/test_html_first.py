"""Public pages ship HTML and CSS without a global JavaScript baseline."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

PUBLIC_HTML_ROUTES = (
    "/",
    "/services",
    "/agents",
    "/transparency",
    "/faq",
    "/terms",
    "/privacy",
    "/abuse",
    "/legal",
    "/status",
    "/order",
)


def test_public_pages_have_no_executable_scripts(client: TestClient) -> None:
    for path in PUBLIC_HTML_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        script_tags = re.findall(r"<script\b[^>]*>", response.text, flags=re.IGNORECASE)
        assert all('type="application/ld+json"' in tag for tag in script_tags), (path, script_tags)
        assert 'type="module"' not in response.text
        assert "htmx" not in response.text.lower()
        assert "hx-" not in response.text
        assert "cmdk" not in response.text.lower()
        assert "jump to" not in response.text.lower()


def test_global_css_is_linked_without_a_module_entry(client: TestClient) -> None:
    response = client.get("/")
    assert "/static/dist/assets/styles-" in response.text
    assert "/static/dist/assets/main-" not in response.text


def test_toolbox_is_the_only_public_page_with_a_page_runtime(client: TestClient) -> None:
    response = client.get("/toolbox")
    assert response.status_code == 200
    assert 'type="module"' in response.text
    assert "/static/dist/assets/toolbox-" in response.text
    assert 'type="application/json"' in response.text


def test_removed_global_javascript_assets_are_absent() -> None:
    root = Path(__file__).resolve().parents[1]
    for removed in (
        "frontend/src/main.ts",
        "frontend/src/order.ts",
        "frontend/src/cmdk.ts",
        "frontend/src/nav.ts",
        "hyrule_web/static/htmx.min.js",
    ):
        assert not (root / removed).exists(), removed
