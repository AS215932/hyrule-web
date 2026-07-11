"""HTML-native responsive navigation rendered from one shared partial."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_header_uses_native_details_mobile_menu(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert '<details class="mobile-nav-menu">' in response.text
    assert '<summary aria-label="Open navigation">' in response.text
    assert "data-nav-toggle" not in response.text
    assert "data-nav-backdrop" not in response.text

    css = (
        Path(__file__).parent.parent / "frontend" / "src" / "styles" / "monochrome.css"
    ).read_text()
    assert ".mobile-nav-menu:not([open]) > nav" in css
    closed_rule = css.split(".mobile-nav-menu:not([open]) > nav", 1)[1].split("}", 1)[0]
    assert "display: none" in closed_rule


def test_nav_links_render_in_desktop_and_mobile_navigation(client: TestClient) -> None:
    response = client.get("/")
    assert response.text.count('href="/services"') >= 2
    assert response.text.count('href="/agents"') >= 2
    assert response.text.count('href="/transparency"') >= 2
    assert response.text.count('href="/status"') >= 2
    assert response.text.count('href="/login"') >= 2
    assert 'href="/order/status"' not in response.text


def test_nav_links_swap_to_dashboard_when_authenticated(client: TestClient) -> None:
    response = client.get("/", cookies={"hyr_sess": "x"})
    assert response.text.count('href="/dashboard"') >= 2
    assert 'href="/login"' not in response.text
