"""/x402-vps, /no-kyc-vps landing pages and /llms-full.txt.

Chain and price copy must come from the live API mocks, never hardcoded.
"""

from __future__ import annotations

import respx
from fastapi.testclient import TestClient

from hyrule_web.config import VM_TIERS
from hyrule_web.seo import build_llms_full_txt, build_llms_txt


def test_x402_vps_renders_faq_breadcrumb_and_comparison(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/x402-vps")
    assert r.status_code == 200
    assert '"FAQPage"' in r.text
    assert '"BreadcrumbList"' in r.text
    assert "Payment-Signature" in r.text
    assert "OpenVPS" in r.text
    assert "/day" in r.text


def test_no_kyc_vps_renders_and_links_policies(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/no-kyc-vps")
    assert r.status_code == 200
    assert '"FAQPage"' in r.text
    assert 'href="/privacy"' in r.text
    assert 'href="/terms"' in r.text


def test_landing_pages_are_in_sitemap_and_footer(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    sitemap = client.get("/sitemap.xml").text
    for path in ("/x402-vps", "/no-kyc-vps", "/llms-full.txt"):
        assert f"https://hyrule.host{path}<" in sitemap
    home = client.get("/").text
    assert 'href="/x402-vps"' in home
    assert 'href="/no-kyc-vps"' in home


def test_llms_txt_links_landing_pages_and_full_doc() -> None:
    text = build_llms_txt(networks=None)
    assert "https://hyrule.host/x402-vps" in text
    assert "https://hyrule.host/no-kyc-vps" in text
    assert "https://hyrule.host/llms-full.txt" in text


def test_llms_full_txt_extends_llms_txt_with_live_prices() -> None:
    base = build_llms_txt(networks=None)
    full = build_llms_full_txt(base, VM_TIERS)
    assert full.startswith(base.rstrip("\n"))
    for tier in VM_TIERS.values():
        assert f"${tier['price']:.2f}/day" in full
    assert "## Common questions" in full


def test_llms_full_route_serves_plain_text(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    r = client.get("/llms-full.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "# Hyrule Cloud" in r.text
    assert "## VM pricing (live)" in r.text
