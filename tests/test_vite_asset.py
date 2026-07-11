"""Issue #14: the vite_asset() Jinja helper — manifest resolution + dev branch."""

from __future__ import annotations

import pytest

from hyrule_web import app as webapp


def test_vite_asset_resolves_payment_entry_from_manifest() -> None:
    html = str(webapp.vite_asset("payment"))
    assert '<script type="module"' in html
    assert "/static/dist/assets/payment-" in html


def test_vite_styles_resolves_css_without_script() -> None:
    html = str(webapp.vite_styles("styles"))
    assert "/static/dist/assets/styles-" in html
    assert '<link rel="stylesheet"' in html
    assert ".css" in html
    assert "<script" not in html


def test_vite_asset_unknown_entry_is_empty() -> None:
    assert str(webapp.vite_asset("does-not-exist")) == ""


def test_vite_asset_dev_server_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webapp.settings, "debug", True)
    monkeypatch.setattr(webapp.settings, "vite_dev_server", "http://localhost:5173")
    html = str(webapp.vite_asset("payment"))
    assert "http://localhost:5173/@vite/client" in html
    assert "http://localhost:5173/frontend/src/payment.ts" in html


def test_vite_styles_dev_server_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webapp.settings, "debug", True)
    monkeypatch.setattr(webapp.settings, "vite_dev_server", "http://localhost:5173")
    html = str(webapp.vite_styles("styles"))
    assert html == (
        '<link rel="stylesheet" '
        'href="http://localhost:5173/frontend/src/styles/app.css">'
    )
