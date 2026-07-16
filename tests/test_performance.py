"""Regression guards for the concrete mobile PageSpeed fixes."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient


def test_html_is_compressed_and_origin_isolated(client: TestClient) -> None:
    response = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["origin-agent-cluster"] == "?1"
    assert response.headers["permissions-policy"] == "tools=(self)"


def test_hashed_assets_are_immutable(client: TestClient) -> None:
    page = client.get("/")
    path = re.search(r'href="(/static/dist/assets/styles-[^"]+\.css)"', page.text)
    assert path is not None
    asset = client.get(path.group(1))
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_base_uses_small_local_brand_and_no_google_fonts(client: TestClient) -> None:
    body = client.get("/").text
    assert "fonts.googleapis.com" not in body
    assert "fonts.gstatic.com" not in body
    assert "/static/icon-512.png" not in body
    assert "/static/icon-96.webp" in body
    icon = Path(__file__).parents[1] / "hyrule_web/static/icon-96.webp"
    assert icon.stat().st_size < 15_000
