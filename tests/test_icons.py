"""Brand icon routes — /favicon.ico + /apple-touch-icon.png served at root.

Browsers and crawlers request these well-known paths directly, not just the
<link>-referenced /static path, so app.py serves them from root too. The files
themselves live under hyrule_web/static/ and are also reachable via /static.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_favicon_ico_route(client: TestClient) -> None:
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert "image/x-icon" in r.headers["content-type"]
    # .ico magic: 00 00 01 00 (reserved + type=1 icon).
    assert r.content[:4] == b"\x00\x00\x01\x00"
    # Brand marks change rarely — the root route caches for a week.
    assert "max-age=604800" in r.headers.get("cache-control", "")


def test_apple_touch_icon_route(client: TestClient) -> None:
    r = client.get("/apple-touch-icon.png")
    assert r.status_code == 200
    assert "image/png" in r.headers["content-type"]
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_apple_touch_icon_precomposed_alias(client: TestClient) -> None:
    """iOS also probes the -precomposed variant; it maps to the same handler."""
    r = client.get("/apple-touch-icon-precomposed.png")
    assert r.status_code == 200
    assert "image/png" in r.headers["content-type"]


def test_icons_reachable_via_static_mount(client: TestClient) -> None:
    """The <link> tags in base.html point at /static/*; that mount must serve
    the same assets the root routes do."""
    for path in ("/static/favicon.ico", "/static/favicon-32.png",
                 "/static/apple-touch-icon.png", "/static/site.webmanifest"):
        assert client.get(path).status_code == 200
