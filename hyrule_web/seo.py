"""SEO foundation: robots.txt, sitemap.xml, llms.txt content."""

from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape

from fastapi import FastAPI
from fastapi.routing import APIRoute

SITE_BASE_URL = "https://hyrule.host"

ROBOTS_TXT = """\
User-agent: *
Allow: /
Disallow: /api/
Disallow: /partials/

# Agent crawlers — explicitly welcome
User-agent: ClaudeBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: GPTBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: PerplexityBot
Allow: /

Sitemap: https://hyrule.host/sitemap.xml
"""

LLMS_TXT = """\
# Hyrule Cloud

> IPv6-native bare-metal VM provisioning on AS215932. Clear daily pricing,
> fast provisioning (~60 seconds), crypto-native checkout via x402. Built
> for developers and AI agents that need infrastructure on demand without
> the usual hosting ceremony.

## Products

- [VM tiers and pricing](https://hyrule.host/services): Starter, Basic,
  Standard, and Performance plans with explicit vCPU / RAM / disk and
  daily USD pricing. SSH root access via your public key.
- [Order a VM](https://hyrule.host/order): single-page order flow.
  Inputs: OS, size, duration (1–365 days), SSH public key, optional
  hostname and custom domain.

## API

- Hyrule Cloud API base URL: published in the OpenAPI schema served by
  the backend. The web frontend at https://hyrule.host proxies
  `/api/*` to the same backend so browser clients hit the same origin.

## Network

- [AS215932](https://as215932.net): the autonomous system Hyrule Cloud
  runs on. IPv6-first; NAT64/DNS64 available for reaching IPv4
  destinations.

## What ships with each VM

- Full SSH root access (ed25519 or RSA public key)
- Global IPv6 with NAT64/DNS64
- Automatic subdomain on `deploy.hyrule.host` (custom domains via AAAA)
- SSH, HTTP, HTTPS open by default; outbound SMTP blocked
- 1–365 day runtimes, extendable, 24-hour grace after expiry
"""


# Paths that exist as FastAPI routes but should not be in the sitemap:
# either non-navigable (API proxy, HTMX partials), per-user dynamic
# (status pages), or POST-only (order review), or empty stubs.
_SITEMAP_EXCLUDE = {"/dashboard", "/robots.txt", "/sitemap.xml"}


def iter_sitemap_paths(app: FastAPI) -> list[str]:
    """Enumerate public, static, GET-able routes for the sitemap."""
    paths: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if "GET" not in route.methods:
            continue
        path = route.path
        if "{" in path:
            continue
        if path.startswith("/api") or path.startswith("/partials"):
            continue
        if path in _SITEMAP_EXCLUDE:
            continue
        paths.add(path)
    paths.add("/llms.txt")
    return sorted(paths)


def render_sitemap_xml(app: FastAPI) -> str:
    today = date.today().isoformat()
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{escape(SITE_BASE_URL + path)}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"  </url>"
        for path in iter_sitemap_paths(app)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
