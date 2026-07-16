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
Disallow: /dashboard
Disallow: /order/manage/
Disallow: /domains/orders/

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

> Full-stack infrastructure that autonomous agents can discover, pay for,
> and provision directly: compute, network intelligence, domains and DNS,
> and network proxy on AS215932. x402 prices and requirements are published
> as machine-readable contracts.

## Agent purchase model

- Discover prices and schemas in `/.well-known/x402.json` and OpenAPI.
- Call the resource normally; HTTP 402 returns exact payment requirements.
- Sign, retry with `X-PAYMENT`, and consume the structured response.
- VM creation returns public status and save-once management URLs.
- Optional accounts use generated handles and recovery credentials.
- No-KYC ordering is available; operational service and payment records still apply.

## Products

- [Service catalog](https://hyrule.host/services): all four service groups —
  compute, network intelligence, domains & DNS, network proxy — with live
  per-endpoint pricing from the x402 manifest.
- [For agents](https://hyrule.host/agents): the x402 golden path, the async
  VM contract (public status poll vs token-gated management URL), MCP server
  config, ClawHub skills, and the full price schedule.
- [Order a VM](https://hyrule.host/order): server-rendered durable quote flow.
- [Search domains](https://hyrule.host/domains): live eligibility, registration,
  renewal pricing, managed DNS, DNSSEC, and transfer policy.
- [Service status](https://hyrule.host/status): current customer-impacting
  health for API checkout, compute, intelligence, domains/DNS, and proxy.
- [About](https://hyrule.host/transparency): operator,
  jurisdiction, host inventory, BGP peering, monitoring stack.
- [FAQ](https://hyrule.host/faq): integration, recovery, IPv6, and operations.
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
- Service status: https://cloud.hyrule.host/v1/status
- Price a durable order (POST): https://cloud.hyrule.host/v1/vm/quote
- Provision a VM (POST, x402): https://cloud.hyrule.host/v1/vm/create
- Domains OpenAPI: https://cloud.hyrule.host/v1/domains/openapi.json
- Check a domain: https://cloud.hyrule.host/v1/domains/check?domain=example.dev
- Create a domain quote (POST): https://cloud.hyrule.host/v1/domains/quotes
- Place a domain order (POST): https://cloud.hyrule.host/v1/domains/orders
- Paid network request: https://cloud.hyrule.host/v1/network/request

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
- Account-owned domains can be attached to a VM as a separate order
- Paid direct/Tor network requests are available through the API
- SSH, HTTP, HTTPS open by default; outbound SMTP blocked
- 1-365 day runtimes, extendable, 24-hour grace after expiry

## Network

- [AS215932](https://as215932.net): IPv6-first autonomous system,
  prefix `2a0c:b641:b50::/44`, RIPE-registered. Transit upstreams listed
  on the transparency page.
"""


_LLMS_TXT_DIAGNOSTICS = """\
## Paid network diagnostics (x402, per-request)

Beyond VMs, the same API sells network-intelligence lookups an agent can
buy per request — $0.001 to $0.10 each, same 402 → sign → retry flow:

- DNS/DNSSEC/propagation: POST /v1/dns/lookup, /v1/dns/propagation
- IP intelligence (geo/ASN/rDNS): POST /v1/ip/lookup
- BGP/routing: POST /v1/bgp/lookup, /v1/path/ping, /v1/path/report
- Registry: POST /v1/rdap/lookup, /v1/whois/lookup
- Web/TLS: POST /v1/web/check, /v1/web/tls/deep
- Mail deliverability: POST /v1/mx/check (SPF/DKIM/DMARC/blacklists)
- Reachability: POST /v1/ports/check, /v1/nat/lookup
- VoIP/SIP: POST /v1/voip/check, /v1/voip/number/lookup
- Anonymous egress: POST /v1/network/request (direct/Tor/I2P/Yggdrasil)

Discovery: every paid endpoint is listed with price in
https://cloud.hyrule.host/.well-known/x402.json (`discoverable` entries
carry machine-readable input/output schemas in their 402 responses).
The diagnostic services (dns, ip, bgp, rdap, whois, web, mx, path, ports,
nat, threat, voip) each describe their product boundary at
`/v1/<service>/capabilities`; the egress endpoint is documented in the
manifest only. OpenClaw skills for these services are being rolled out on
ClawHub under the `hyrule-` prefix — check there for `hyrule-cloud` and
`hyrule-network-intel` availability.

Golden path (diagnostic), against https://cloud.hyrule.host:

    POST /v1/dns/lookup {"name":"example.com","type":"AAAA"}  -> 402
    # sign EIP-3009 for the quoted amount (USDC, $0.001)
    POST /v1/dns/lookup + X-PAYMENT  -> 200 diagnostic evidence
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
            text += f"- Native VM checkout rails currently enabled: {', '.join(native_list)}.\n"
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
            "- Native VM checkout rails currently enabled: "
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
    diagnostics_live: bool = True,
) -> str:
    """Compose llms.txt from the live config snapshot.

    `networks` and `native` are from `/v1/payments/networks`. Pass networks
    as None to render a "ask the API" placeholder section instead.
    `diagnostics_live` should be False when the catalog came from a stale
    cache rather than live discovery.
    """
    network_list = list(networks) if networks is not None else None
    text = (
        _LLMS_TXT_PREAMBLE
        + "\n"
        + _render_payment_section(network_list, native=native)
        + "\n"
        + _LLMS_TXT_WHAT_SHIPS
    )
    # Only advertise the paid diagnostics suite when FRESH live discovery
    # succeeded AND at least one EVM x402 chain is enabled: the golden path
    # requires signing EIP-3009 USDC, so an SVM/native-only catalog (or a
    # stale cached one) would send agents to endpoints they cannot pay for.
    has_x402_chain = network_list is not None and any(
        n.get("family") == "evm" for n in network_list
    )
    if has_x402_chain and diagnostics_live:
        text += "\n" + _LLMS_TXT_DIAGNOSTICS
    return text


# Paths that exist as FastAPI routes but should not be in the sitemap:
# either non-navigable (API proxy), per-user dynamic
# (status pages), or POST-only (order review), or auth-gated surfaces.
_SITEMAP_EXCLUDE = {
    "/dashboard",
    "/robots.txt",
    "/sitemap.xml",
    "/order/status",
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
