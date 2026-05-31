"""Issue #8 (Phase 6, PR 1): the reachable mobile-nav drawer in base.html.

base.html renders an accessible hamburger + off-canvas drawer alongside the
desktop ``.site-nav``, both including the shared ``_nav_links.html`` partial so
the two link lists never drift. The disclosure behaviour itself is unit-tested
in ``frontend/src/nav.test.ts``; here we only assert the server-rendered markup.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_header_has_accessible_mobile_nav_toggle(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "data-nav-toggle" in r.text
    assert 'aria-controls="mobile-nav"' in r.text
    assert 'aria-expanded="false"' in r.text


def test_mobile_nav_drawer_and_backdrop_render(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="mobile-nav"' in r.text
    assert "data-nav-backdrop" in r.text
    assert "data-nav-close" in r.text


def test_nav_links_included_in_both_navs_when_logged_out(client: TestClient) -> None:
    """The shared partial is included in the desktop nav AND the drawer, so each
    link renders at least twice; logged-out shows Login (not Dashboard)."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.text.count('href="/services"') >= 2
    assert r.text.count('href="/order/status"') >= 2
    assert r.text.count('href="/login"') >= 2
    assert 'href="/dashboard"' not in r.text


def test_nav_links_swap_to_dashboard_when_authed(client: TestClient) -> None:
    """With a session cookie the partial swaps Login -> Dashboard in both navs."""
    r = client.get("/", cookies={"hyr_sess": "x"})
    assert r.status_code == 200
    assert r.text.count('href="/dashboard"') >= 2
    assert 'href="/login"' not in r.text
