"""SEO foundation: robots.txt, sitemap.xml, llms.txt content.

Block G principle: never advertise a feature that isn't live. `LLMS_TXT` is
built at request time from the backend's live `/v1/payments/networks` rather
than a hardcoded chain list, so agents see exactly what they can actually
pay with today.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any
from xml.sax.saxutils import escape

from fastapi import FastAPI
from fastapi.routing import APIRoute

SITE_BASE_URL = "https://hyrule.host"

ROBOTS_TXT = """\
User-agent: *
Allow: /
Disallow: /api/
Disallow: /partials/
Disallow: /dashboard
Disallow: /order/manage/

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


_LLMS_TXT_PREAMBLE = """\
# Hyrule Cloud

> IPv6-native bare-metal VM provisioning on AS215932. No-KYC: a random
> account handle and a password you set, or pay anonymously with crypto.
> Clear daily pricing, ~60s provisioning, x402 for AI agents. The web
> frontend is a thin shell over the API at /api/* (same origin).

## Anonymity guarantees

- No email collected, ever.
- No phone, no name, no address.
- Account handles are random `H<10 hex>`; you set the password.
- Anon checkout: no account at all, one-shot management URL.
- We store: VM config you provide, your SSH public key, the payer wallet
  address (x402 EVM only), a sha256 of your /64 IPv6 prefix for abuse rate
  limiting. That's it.

## Products

- [VM tiers and pricing](https://hyrule.host/services): explicit vCPU /
  RAM / disk and daily USD pricing. SSH root access via your public key.
- [Order a VM](https://hyrule.host/order): single-page order flow.
- [Transparency](https://hyrule.host/transparency): operator,
  jurisdiction, host inventory, BGP peering, monitoring stack.
- [FAQ](https://hyrule.host/faq): no-KYC details, recovery, IPv6 reachability.
- [Terms](https://hyrule.host/terms), [Privacy](https://hyrule.host/privacy),
  [Abuse](https://hyrule.host/abuse), [Legal](https://hyrule.host/legal):
  service rules, data handling, notice/action flow, contact points.

## API

Canonical API host: https://cloud.hyrule.host (the web frontend at
https://hyrule.host proxies `/api/*` to it, so browser clients hit the same
origin). Key URLs:

- OpenAPI schema: https://cloud.hyrule.host/openapi.json
- x402 service manifest: https://cloud.hyrule.host/.well-known/x402.json
- VM catalog: https://cloud.hyrule.host/v1/products/vms
- Price a durable order (POST): https://cloud.hyrule.host/v1/vm/quote
- Provision a VM (POST, x402): https://cloud.hyrule.host/v1/vm/create

Golden path (agent), all against https://cloud.hyrule.host:

    GET  /.well-known/x402.json
    GET  /v1/products/vms
    POST /v1/vm/quote  -> {quote_id, amount_usd, expires_at}
    POST /v1/vm/create {quote_id}  -> 402 + X-PAYMENT-REQUIRED
    # sign EIP-3009 TransferWithAuthorization for amount_usd
    POST /v1/vm/create {quote_id} + X-PAYMENT  -> 202 {vm_id, management_token}
    GET  /v1/vm/{vm_id}/status  -> poll to ready
"""


_LLMS_TXT_WHAT_SHIPS = """\
## What ships with each VM

- Full SSH root access (ed25519 or RSA public key)
- Global IPv6 with NAT64/DNS64 to reach IPv4 destinations
- Automatic subdomain on `deploy.hyrule.host`
- Custom domains and domain registration are beta / support-assisted
- SSH, HTTP, HTTPS open by default; outbound SMTP blocked
- 1-365 day runtimes, extendable, 24-hour grace after expiry

## Network

- [AS215932](https://as215932.net): IPv6-first autonomous system,
  prefix `2a0c:b641:b50::/44`, RIPE-registered. Transit upstreams listed
  on the transparency page.
"""


def _render_payment_section(
    networks: Iterable[dict[str, Any]] | None,
    native: Iterable[str] | None = None,
) -> str:
    """Build the payment-methods section from live network data.

    If `networks` is None (backend unreachable), we render a deliberately
    vague note instead of guessing a list. Better to under-promise than to
    advertise a chain that may have been disabled.
    """
    if networks is None:
        return (
            "## Payment\n\n"
            "- x402 USDC on facilitator-verified EVM chains. Query "
            "`/api/v1/payments/networks` for the live list — this document "
            "is rendered against backend state at request time.\n"
            "- Native crypto rails are listed only when the backend advertises "
            "them in `/api/v1/payments/networks`.\n"
        )

    network_list = list(networks)
    native_list = [str(x).upper() for x in native or []]
    if not network_list:
        text = (
            "## Payment\n\n"
            "- No EVM chains are currently enabled. Check "
            "`/api/v1/payments/networks` for the live status.\n"
        )
        if native_list:
            text += f"- Native rails currently enabled: {', '.join(native_list)}.\n"
        return text

    lines = ["## Payment", ""]
    lines.append("- x402 USDC on the following facilitator-verified chains:")
    for n in network_list:
        display = n.get("display_name") or n.get("key", "?")
        caip2 = n.get("caip2", "")
        chain_id = n.get("chain_id")
        suffix = f" (chain id {chain_id})" if chain_id else ""
        lines.append(f"    - {display} — `{caip2}`{suffix}")
    if native_list:
        lines.append(
            "- Native intent rails currently enabled: "
            f"{', '.join(native_list)} (`POST /api/v1/intent/create`)."
        )
    else:
        lines.append(
            "- BTC/XMR are not advertised unless the native intent rail is live "
            "in the backend catalog."
        )
    lines.append("")
    return "\n".join(lines)


def build_llms_txt(
    networks: Iterable[dict[str, Any]] | None = None,
    native: Iterable[str] | None = None,
) -> str:
    """Compose llms.txt from the live config snapshot.

    `networks` and `native` are from `/v1/payments/networks`. Pass networks
    as None to render a "ask the API" placeholder section instead.
    """
    return (
        _LLMS_TXT_PREAMBLE
        + "\n"
        + _render_payment_section(networks, native=native)
        + "\n"
        + _LLMS_TXT_WHAT_SHIPS
    )


# Paths that exist as FastAPI routes but should not be in the sitemap:
# either non-navigable (API proxy, HTMX partials), per-user dynamic
# (status pages), or POST-only (order review), or auth-gated surfaces.
_SITEMAP_EXCLUDE = {
    "/dashboard",
    "/robots.txt",
    "/sitemap.xml",
    # Auth surfaces are reachable but uninteresting to crawlers.
    "/logout",
}


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
        if path.startswith("/dashboard"):
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


# Backwards-compat: a hardcoded LLMS_TXT used to live here. Keeping the name
# importable as the placeholder (no-networks-known) variant so any external
# scrape that imported it directly still gets a sensible string.
LLMS_TXT = build_llms_txt(networks=None)
