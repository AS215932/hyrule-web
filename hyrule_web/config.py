"""Configuration for the Hyrule Cloud web frontend."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings

# FALLBACK tier catalog, used only when the live GET /v1/products/vms fetch
# fails (see app._refresh_products). The API is the source of truth for what
# actually gets provisioned — this table once drifted (xs shipped 1 GB while
# the site still said 512 MB), which is why pages now render live products.
VM_TIERS: dict[str, dict[str, Any]] = {
    "xs": {"name": "Starter", "vcpu": 1, "ram_mb": 1024, "disk_gb": 10, "price": 0.05},
    "sm": {"name": "Basic", "vcpu": 1, "ram_mb": 1024, "disk_gb": 20, "price": 0.10},
    "md": {"name": "Standard", "vcpu": 2, "ram_mb": 2048, "disk_gb": 40, "price": 0.20},
    "lg": {"name": "Performance", "vcpu": 4, "ram_mb": 4096, "disk_gb": 80, "price": 0.40},
}

# FALLBACK x402 resource catalog for the /services and /agents pages, used when
# the live /.well-known/x402.json fetch fails. Mirrors the published manifest
# (path, method, one-line description, minimum price in USD). `group` buckets
# the rows into the four service pillars for rendering.
X402_RESOURCES_FALLBACK: list[dict[str, Any]] = [
    {"path": "/v1/vm/create", "method": "POST", "group": "compute",
     "description": "Provision a bare VM with SSH access", "min_price": "0.05"},
    {"path": "/v1/domains/orders", "method": "POST", "group": "domains",
     "description": "Place an account-owned domain registration or renewal", "min_price": "6.00"},
    {"path": "/v1/network/request", "method": "POST", "group": "proxy",
     "description": "Proxied network request over Direct, Tor, I2P, or Yggdrasil",
     "min_price": "0.01"},
    {"path": "/v1/bgp/lookup", "method": "POST", "group": "intel",
     "description": "BGP/routing lookup by prefix, IP, or ASN", "min_price": "0.005"},
    {"path": "/v1/bgp/jobs", "method": "POST", "group": "intel",
     "description": "Historical BGPStream job over RouteViews / RIPE RIS", "min_price": "0.05"},
    {"path": "/v1/ip/lookup", "method": "POST", "group": "intel",
     "description": "IP geolocation, ASN/ISP, reverse DNS, reputation", "min_price": "0.003"},
    {"path": "/v1/dns/lookup", "method": "POST", "group": "intel",
     "description": "DNS lookup, reverse lookup, DNSSEC validation", "min_price": "0.001"},
    {"path": "/v1/dns/propagation", "method": "POST", "group": "intel",
     "description": "Propagation comparison across public resolvers", "min_price": "0.001"},
    {"path": "/v1/dns/recommend-records", "method": "POST", "group": "intel",
     "description": "DNS record recommendations for web, mail, and more", "min_price": "0.001"},
    {"path": "/v1/rdap/lookup", "method": "POST", "group": "intel",
     "description": "Structured RDAP lookup for domains, IPs, ASNs", "min_price": "0.003"},
    {"path": "/v1/whois/lookup", "method": "POST", "group": "intel",
     "description": "Legacy WHOIS lookup for domains, IPs, prefixes", "min_price": "0.005"},
    {"path": "/v1/web/check", "method": "POST", "group": "intel",
     "description": "Web reachability, HTTP/HTTPS, TLS certificate check", "min_price": "0.005"},
    {"path": "/v1/web/tls/deep", "method": "POST", "group": "intel",
     "description": "SSL-Labs-style deep TLS scan and grade", "min_price": "0.10"},
    {"path": "/v1/mx/check", "method": "POST", "group": "intel",
     "description": "MXToolbox-compatible mail diagnostics", "min_price": "0.005"},
    {"path": "/v1/mx/bounce/parse", "method": "POST", "group": "intel",
     "description": "Bounce/rejection parser with likely causes", "min_price": "0.005"},
    {"path": "/v1/mx/recommend-records", "method": "POST", "group": "intel",
     "description": "SPF, DKIM, DMARC, MTA-STS, TLS-RPT recommendations", "min_price": "0.005"},
    {"path": "/v1/mx/jobs", "method": "POST", "group": "intel",
     "description": "Full mail-delivery diagnostic report", "min_price": "0.03"},
    {"path": "/v1/ports/check", "method": "POST", "group": "intel",
     "description": "Outside-in service reachability check", "min_price": "0.003"},
    {"path": "/v1/nat/lookup", "method": "POST", "group": "intel",
     "description": "Server-side CGNAT/NAT hint report", "min_price": "0.003"},
    {"path": "/v1/nat/port-forward/check", "method": "POST", "group": "intel",
     "description": "Outside-in NAT port-forward reachability", "min_price": "0.005"},
    {"path": "/v1/voip/check", "method": "POST", "group": "intel",
     "description": "SIP DNS, SIP TLS, OPTIONS, STUN/TURN diagnostics", "min_price": "0.01"},
]

# FALLBACK per-route proxy pricing (live source: GET /v1/pricing proxy_prices).
PROXY_PRICES_FALLBACK: dict[str, str] = {
    "direct": "$0.01/request",
    "tor": "$0.05/request",
    "i2p": "$0.05/request",
    "yggdrasil": "$0.03/request",
}

DEFAULT_OS_TEMPLATES: list[dict[str, Any]] = [
    {"name": "debian-13", "description": "Debian 13 (Trixie)", "default": True},
    {"name": "alpine-3.21", "description": "Alpine Linux 3.21", "default": False},
    {"name": "freebsd-14", "description": "FreeBSD 14.2", "default": False},
]


class Settings(BaseSettings):
    api_base_url: str = "http://localhost:8402"
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # Wave 2 (Block A1): gate the auth UI behind a flag so the deploy can be
    # rolled back to "templates dark" by flipping HYRULE_WEB_ENABLE_AUTH_UI=false
    # without redeploying the backend or running a migration. When false the
    # /signup, /login, /recover, /dashboard routes return 404 and the header
    # falls back to the pre-Wave-2 nav (no Login / Dashboard pills).
    enable_auth_ui: bool = True

    # Issue #14 frontend build: in prod, templates load hashed assets from the
    # committed Vite manifest under static/dist/. For local dev, set this to the
    # Vite dev server origin (e.g. http://localhost:5173) AND debug=true to load
    # modules from it with HMR instead of the built bundle.
    vite_dev_server: str = ""

    # Issue #14 (Phase 4): WalletConnect/Reown projectId for mobile EVM payments.
    # This is a PUBLIC client id (Reown dashboard), surfaced to the browser via a
    # <meta> tag — NOT a secret. Empty disables the mobile WalletConnect path
    # (the injected-wallet + BTC/XMR paths still work).
    walletconnect_project_id: str = ""

    model_config = {"env_prefix": "HYRULE_WEB_"}


settings = Settings()
