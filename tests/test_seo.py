"""SEO helpers: iter_sitemap_paths filtering + render_sitemap_xml shape.

Each of the 5 filter branches in iter_sitemap_paths gets one positive and one
negative test via a synthetic FastAPI app — exercising it through the real
hyrule-web app would couple these unit tests to the route table.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse

from hyrule_web.seo import (
    LLMS_TXT,
    ROBOTS_TXT,
    SITE_BASE_URL,
    iter_sitemap_paths,
    render_sitemap_xml,
)


def _build_app() -> FastAPI:
    """Synthetic app covering every iter_sitemap_paths filter branch."""
    a = FastAPI()

    @a.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return "ok"

    @a.get("/about", response_class=HTMLResponse)
    async def about() -> str:
        return "ok"

    # POST-only — filtered.
    @a.post("/submit")
    async def submit() -> dict[str, bool]:
        return {"ok": True}

    # Parameterized — filtered.
    @a.get("/users/{uid}", response_class=HTMLResponse)
    async def user(uid: str) -> str:
        return uid

    # Under /api — filtered.
    @a.get("/api/data")
    async def api_data() -> dict[str, int]:
        return {"x": 1}

    # Under /partials — filtered.
    @a.get("/partials/x", response_class=HTMLResponse)
    async def partial_x() -> str:
        return "ok"

    # In the explicit exclude set — filtered.
    @a.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> str:
        return "ok"

    # In the exclude set — filtered.
    @a.get("/robots.txt", response_class=PlainTextResponse)
    async def robots() -> str:
        return "ok"

    return a


def test_iter_sitemap_paths_includes_static_get_routes() -> None:
    paths = iter_sitemap_paths(_build_app())
    assert "/" in paths
    assert "/about" in paths


def test_iter_sitemap_paths_excludes_post_only() -> None:
    assert "/submit" not in iter_sitemap_paths(_build_app())


def test_iter_sitemap_paths_excludes_parameterized() -> None:
    paths = iter_sitemap_paths(_build_app())
    assert not any("{" in p for p in paths)
    assert "/users/{uid}" not in paths


def test_iter_sitemap_paths_excludes_api_and_partials() -> None:
    paths = iter_sitemap_paths(_build_app())
    assert "/api/data" not in paths
    assert "/partials/x" not in paths


def test_iter_sitemap_paths_excludes_dashboard_and_robots() -> None:
    paths = iter_sitemap_paths(_build_app())
    assert "/dashboard" not in paths
    assert "/robots.txt" not in paths


def test_iter_sitemap_paths_always_includes_llms() -> None:
    a = FastAPI()  # empty app
    assert "/llms.txt" in iter_sitemap_paths(a)


def test_iter_sitemap_paths_returns_sorted() -> None:
    paths = iter_sitemap_paths(_build_app())
    assert paths == sorted(paths)


def test_render_sitemap_xml_is_well_formed() -> None:
    xml = render_sitemap_xml(_build_app())
    root = ET.fromstring(xml)
    assert root.tag.endswith("urlset")
    locs = [el.text for el in root.iter() if el.tag.endswith("loc")]
    assert f"{SITE_BASE_URL}/" in locs
    assert f"{SITE_BASE_URL}/about" in locs
    assert f"{SITE_BASE_URL}/llms.txt" in locs


def test_render_sitemap_xml_has_no_lastmod_and_is_byte_stable() -> None:
    """<lastmod> used to stamp date.today() on every URL, so the document
    changed byte-wise daily and the seo-agent's sha256-change-gated IndexNow
    pinger fired with an unchanged URL set. The render must be deterministic
    for a given route table."""
    a = _build_app()
    xml = render_sitemap_xml(a)
    assert "lastmod" not in xml
    root = ET.fromstring(xml)
    urls = [el for el in root.iter() if el.tag.endswith("url")]
    assert urls
    for u in urls:
        children = {el.tag.split("}")[-1] for el in u}
        assert children == {"loc"}
    assert render_sitemap_xml(a) == xml


def test_robots_txt_contains_sitemap_pointer_and_agent_allowlist() -> None:
    assert "Sitemap: https://hyrule.host/sitemap.xml" in ROBOTS_TXT
    for ua in ("ClaudeBot", "OAI-SearchBot", "GPTBot", "Google-Extended", "PerplexityBot"):
        assert ua in ROBOTS_TXT
    assert "Disallow: /api/" in ROBOTS_TXT
    assert "/partials/" not in ROBOTS_TXT


def test_llms_txt_is_markdown_with_required_sections() -> None:
    assert LLMS_TXT.startswith("# Hyrule Cloud")
    assert "## Products" in LLMS_TXT
    assert "https://hyrule.host/services" in LLMS_TXT
    assert "https://hyrule.host/order" in LLMS_TXT
    assert "https://hyrule.host/abuse" in LLMS_TXT
    assert "Native crypto rails are listed only" in LLMS_TXT


def test_build_llms_txt_announce_section_is_gated_and_additive() -> None:
    """Block G: the registry/skills listings are not published yet, so the
    announce section defaults OFF, and turning it on must only append — the
    rest of the document stays byte-identical."""
    from hyrule_web.seo import build_llms_txt

    off = build_llms_txt(networks=None)
    on = build_llms_txt(networks=None, announce=True)
    assert "## Agent integrations" not in off
    assert "host.hyrule/hyrule-cloud" not in off
    assert "clawhub" not in off.lower()
    assert on.startswith(off)
    assert "## Agent integrations" in on
    assert "https://cloud.hyrule.host/.well-known/agent-card.json" in on
    assert "host.hyrule/hyrule-cloud" in on
    assert "clawhub.ai" in on
