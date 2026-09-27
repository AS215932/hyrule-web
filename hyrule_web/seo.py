"""SEO foundation: robots.txt, sitemap.xml, llms.txt content.

Block G principle: never advertise a feature that isn't live. `LLMS_TXT` is
built at request time from the backend's live `/v1/payments/networks` rather
than a hardcoded chain list, so agents see exactly what they can actually
pay with today. The same rule governs the product list: a service group is
only named here when the API's enabled-only OpenAPI actually advertises a
payable operation for it (see `build_llms_txt(domains_live=...)`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from xml.sax.saxutils import escape

from fastapi import FastAPI
from fastapi.routing import APIRoute

SITE_BASE_URL = "https://hyrule.host"

# hyrule.host is the brand/marketing origin agents discover first; every
# machine-readable contract is authored on the canonical API host. Agent-facing
# copy must reference these ABSOLUTELY: a relative `/.well-known/x402.json` in a
# document served from hyrule.host resolves against the brand origin, which is
# how the first live dogfood run dead-ended on a 404.
CLOUD_BASE_URL = "https://cloud.hyrule.host"
CLOUD_OPENAPI_URL = f"{CLOUD_BASE_URL}/openapi.json"
CLOUD_X402_MANIFEST_URL = f"{CLOUD_BASE_URL}/.well-known/x402.json"
CLOUD_AGENT_CARD_URL = f"{CLOUD_BASE_URL}/.well-known/agent-card.json"

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


_DOMAIN_KEY_URLS = f"""\
- Domains OpenAPI: {CLOUD_BASE_URL}/v1/domains/openapi.json
- Check a domain: {CLOUD_BASE_URL}/v1/domains/check?domain=example.dev
- Create a domain quote (POST): {CLOUD_BASE_URL}/v1/domains/quotes
- Place a domain order (POST): {CLOUD_BASE_URL}/v1/domains/orders
"""

_DOMAIN_PRODUCT_ENTRY = """\
- [Search domains](https://hyrule.host/domains): live eligibility, registration,
  renewal pricing, managed DNS, DNSSEC, and transfer policy.
"""

# Rendered only while the enabled x402 catalog has no payable domain operation.
# The endpoints exist but answer 503 (registrar provider unconfigured), and the
# API's own OpenAPI description says domain registration is deferred from the
# launch catalog — so agents get told plainly instead of being sent to a URL
# they cannot buy from.
_DOMAINS_DEFERRED = """\
## Not yet launched

- Domain registration, transfers, and managed DNS are deferred from the current
  launch catalog. The `/v1/domains/*` endpoints are not payable today, so this
  document does not list them as an agent product. They reappear automatically
  once the enabled x402 catalog advertises a payable domain operation.
"""


_INTRO_WITH_DOMAINS = """\
> Full-stack infrastructure that autonomous agents can discover, pay for,
> and provision directly: compute, network intelligence, domains and DNS,
> and network proxy on AS215932. x402 prices and requirements are published
> as machine-readable contracts.
"""

_INTRO_WITHOUT_DOMAINS = """\
> Full-stack infrastructure that autonomous agents can discover, pay for,
> and provision directly: compute, network intelligence, and network proxy
> on AS215932. x402 prices and requirements are published as
> machine-readable contracts.
"""

_CATALOG_ENTRY_WITH_DOMAINS = """\
- [Service catalog](https://hyrule.host/services): all four service groups —
  compute, network intelligence, domains & DNS, network proxy — with live
  per-endpoint pricing from enabled-only OpenAPI.
"""

_CATALOG_ENTRY_WITHOUT_DOMAINS = """\
- [Service catalog](https://hyrule.host/services): every live service group —
  compute, network intelligence, network proxy — with live per-endpoint
  pricing from enabled-only OpenAPI.
"""


def _render_preamble(domains_live: bool) -> str:
    """Compose the static head of llms.txt against live product availability."""
    intro = _INTRO_WITH_DOMAINS if domains_live else _INTRO_WITHOUT_DOMAINS
    catalog_entry = (
        _CATALOG_ENTRY_WITH_DOMAINS if domains_live else _CATALOG_ENTRY_WITHOUT_DOMAINS
    )
    domain_product = _DOMAIN_PRODUCT_ENTRY if domains_live else ""
    domain_key_urls = _DOMAIN_KEY_URLS if domains_live else ""
    deferred = "" if domains_live else "\n" + _DOMAINS_DEFERRED
    return f"""\
# Hyrule Cloud

{intro}
## Agent purchase model

- Discover prices and schemas in the x402 manifest at
  {CLOUD_X402_MANIFEST_URL} and in the OpenAPI
  document at {CLOUD_OPENAPI_URL}. Both live on the
  API host — resolve them absolutely, not against this document's origin.
- Call the resource normally; HTTP 402 returns exact payment requirements.
- Sign, retry with `Payment-Signature`, and consume the structured response.
- VM creation returns public status and save-once management URLs.
- Optional accounts use generated handles and recovery credentials.
- No-KYC ordering is available; operational service and payment records still apply.

## Products

{catalog_entry}\
- [Toolbox](https://hyrule.host/toolbox): browser-wallet and WebMCP access to
  every currently enabled paid diagnostic.
- [For agents](https://hyrule.host/agents): direct x402 and browser-agent paths,
  including autonomous wallet settlement through WebMCP.
- [Order a VM](https://hyrule.host/order): server-rendered durable quote flow.
{domain_product}\
- [Service status](https://hyrule.host/status): current customer-impacting
  health for API checkout, compute, intelligence, domains/DNS, and proxy.
- [About & policy](https://hyrule.host/about): mission, operating principles,
  abuse-handling posture, and links to the authoritative service policies.
- [FAQ](https://hyrule.host/faq): integration, recovery, IPv6, and operations.
- [Terms](https://hyrule.host/terms), [Privacy](https://hyrule.host/privacy),
  [Abuse](https://hyrule.host/abuse), [Legal](https://hyrule.host/legal):
  service rules, data handling, notice/action flow, contact points.

## API

Canonical API host: {CLOUD_BASE_URL} (the web frontend at
{SITE_BASE_URL} proxies `/api/*` to it, so browser clients hit the same
origin). The brand origin's `/openapi.json` and `/.well-known/x402.json`
redirect here rather than publishing a second, divergent contract. Key URLs:

- OpenAPI schema: {CLOUD_OPENAPI_URL}
- x402 service manifest: {CLOUD_X402_MANIFEST_URL}
- VM catalog: {CLOUD_BASE_URL}/v1/products/vms
- Service status: {CLOUD_BASE_URL}/v1/status
- Price a durable order (POST): {CLOUD_BASE_URL}/v1/vm/quote
- Provision a VM (POST, x402): {CLOUD_BASE_URL}/v1/vm/create
{domain_key_urls}\
- Paid network request: {CLOUD_BASE_URL}/v1/network/request

Golden path (agent), all against {CLOUD_BASE_URL}:

    GET  /.well-known/x402.json
    GET  /v1/products/vms
    POST /v1/vm/quote  -> {{quote_id, amount_usd, expires_at}}
    POST /v1/vm/create {{quote_id}}  -> 402 + Payment-Required
    # sign EIP-3009 TransferWithAuthorization for amount_usd
    POST /v1/vm/create {{quote_id}} + Payment-Signature  -> 202 {{vm_id, management_token}}
    GET  /v1/vm/{{vm_id}}/status  -> poll to ready
{deferred}"""


def _render_what_ships(domains_live: bool) -> str:
    domain_attach = (
        "- Account-owned domains can be attached to a VM as a separate order\n"
        if domains_live
        else ""
    )
    return f"""\
## What ships with each VM

- Full SSH root access (ed25519 or RSA public key)
- Global IPv6 with NAT64/DNS64 to reach IPv4 destinations
- Automatic subdomain on `deploy.hyrule.host`
{domain_attach}\
- Paid direct/Tor network requests are available through the API
- SSH, HTTP, HTTPS open by default; outbound SMTP blocked
- 1-365 day runtimes, extendable, 24-hour grace after expiry

## Network

- [AS215932](https://as215932.net): the current source for Hyrule Cloud's
  routing, peering, addressing, and infrastructure details.
"""


def _render_tools_section(tools: Iterable[dict[str, Any]]) -> str:
    rows = [tool for tool in tools if isinstance(tool, dict)]
    if not rows:
        return ""
    lines = [
        "## Enabled x402 operations",
        "",
        "This list is generated from the API's enabled-only OpenAPI document.",
        "Tagged diagnostics can also be run at https://hyrule.host/toolbox.",
        "",
    ]
    for tool in rows:
        method = str(tool.get("method", "POST"))
        path = str(tool.get("path", ""))
        description = str(tool.get("description") or tool.get("title") or path)
        price = str(tool.get("price_display", "Live 402 quote"))
        surface = "toolbox" if tool.get("executable") else "API"
        lines.append(f"- `{method} {path}` — {description} ({price}; {surface})")
    lines.extend(
        [
            "",
            "Payment uses the exact requirements returned by HTTP 402; discovery prices",
            "are estimates. Browser agents can quote, sign, pay, and consume results with",
            "WebMCP. Headless agents should call https://cloud.hyrule.host directly.",
            "",
        ]
    )
    return "\n".join(lines)


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


# Block G: rendered only behind Settings.enable_llms_announce. The MCP registry
# entry and ClawHub skill listings are prepared but NOT published yet — turning
# the flag on before they exist would send agents to registry lookups that 404.
_ANNOUNCE_SECTION = f"""\
## Agent integrations

- Agent card (A2A discovery): {CLOUD_AGENT_CARD_URL}
  (mirrored at {SITE_BASE_URL}/.well-known/agent-card.json)
- MCP registry: `host.hyrule/hyrule-cloud`
- ClawHub skills: https://clawhub.ai/skills/hyrule-cloud (umbrella; per-service
  skills such as `hyrule-network-intel` are listed from the same publisher).
"""


def build_llms_txt(
    networks: Iterable[dict[str, Any]] | None = None,
    native: Iterable[str] | None = None,
    diagnostics_live: bool = True,
    tools: Iterable[dict[str, Any]] | None = None,
    domains_live: bool = False,
    announce: bool = False,
) -> str:
    """Compose llms.txt from the live config snapshot.

    `networks` and `native` are from `/v1/payments/networks`. Pass networks
    as None to render a "ask the API" placeholder section instead.
    `diagnostics_live` should be False when the catalog came from a stale
    cache rather than live discovery.
    `domains_live` must come from the enabled x402 catalog (a payable
    `/v1/domains/*` operation in the API's OpenAPI document) and defaults to
    False so an unknown state never markets the deferred domain product.
    `announce` (Settings.enable_llms_announce) appends the registry/skills
    section and defaults to False until those listings are published.
    """
    network_list = list(networks) if networks is not None else None
    text = (
        _render_preamble(domains_live)
        + "\n"
        + _render_payment_section(network_list, native=native)
        + "\n"
        + _render_what_ships(domains_live)
    )
    # Only advertise the paid diagnostics suite when FRESH live discovery
    # succeeded AND at least one EVM x402 chain is enabled: the golden path
    # requires signing EIP-3009 USDC, so an SVM/native-only catalog (or a
    # stale cached one) would send agents to endpoints they cannot pay for.
    has_x402_chain = network_list is not None and any(
        n.get("family") == "evm" for n in network_list
    )
    if has_x402_chain and diagnostics_live and tools is not None:
        section = _render_tools_section(tools)
        if section:
            text += "\n" + section
    if announce:
        text += "\n" + _ANNOUNCE_SECTION
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
    # Legacy alias; /about is the canonical policy page.
    "/transparency",
    # Machine discovery URIs that redirect to the canonical API host. They are
    # for agents resolving a well-known path, not pages to index here.
    "/openapi.json",
    "/.well-known/x402.json",
    # Mirrored agent card + IndexNow key file: machine artifacts, not pages.
    "/.well-known/agent-card.json",
    "/indexnow.txt",
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
    # No <lastmod>: stamping every URL with date.today() made the document
    # change byte-wise daily, which defeated the seo-agent's sha256-gated
    # IndexNow pinger (an unchanged URL set looked "changed" every day).
    # Sitemaps are valid without it; the render is deterministic for a given
    # route table.
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{escape(SITE_BASE_URL + path)}</loc>\n"
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
