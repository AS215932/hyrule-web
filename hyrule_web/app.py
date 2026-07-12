"""Hyrule Cloud web frontend — lightweight, server-rendered, Tor-friendly."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import httpx
import structlog
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .config import (
    DEFAULT_OS_TEMPLATES,
    PROXY_PRICES_FALLBACK,
    VM_TIERS,
    X402_RESOURCES_FALLBACK,
    settings,
)
from .seo import ROBOTS_TXT, build_llms_txt, render_sitemap_xml

# Newline-delimited JSON to stdout per AS215932's application logging
# contract (hyrule-infra/docs/application-logging.md). systemd-journald
# captures it; the host's Vector agent ships to Loki.
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.contextvars.merge_contextvars,
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    cache_logger_on_first_use=True,
)
log = structlog.get_logger().bind(service="hyrule-web")

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=30,
    )
    yield
    await app.state.http.aclose()


app = FastAPI(title="Hyrule Cloud", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------------------------------------------------------------------------
# Vite asset manifest (issue #14)
#
# The frontend is built by Vite into static/dist/ with a manifest mapping entry
# names to hashed filenames. `vite_asset()` renders the <script>/<link> tags for
# an entry so templates don't hardcode hashed names. The built bundle is
# committed and shipped by the Ansible deploy (no Node on the web host).
# ---------------------------------------------------------------------------

_DIST_DIR = BASE_DIR / "static" / "dist"
_VITE_MANIFEST_PATH = _DIST_DIR / ".vite" / "manifest.json"
# Friendly entry aliases → manifest keys (the Vite rollup input paths).
_VITE_ENTRIES = {
    "styles": "frontend/src/styles/app.css",
    "payment": "frontend/src/payment.ts",
    "status": "frontend/src/status.ts",
    "secrets": "frontend/src/secret-copy.ts",
}


@lru_cache(maxsize=1)
def _vite_manifest() -> dict[str, Any]:
    try:
        data: Any = json.loads(_VITE_MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        # No build present (e.g. fresh checkout before `npm run build`): render
        # nothing rather than 500. CI's drift guard ensures dist/ is committed.
        log.warning("vite_manifest_missing", path=str(_VITE_MANIFEST_PATH))
        return {}
    return data if isinstance(data, dict) else {}


def vite_asset(entry: str) -> Markup:
    """Render the module <script> (+ its CSS and preloads) for a Vite entry.

    `entry` is a friendly alias (see `_VITE_ENTRIES`) or a raw manifest key.
    In dev (settings.debug + settings.vite_dev_server) it points at the Vite dev
    server for HMR instead of the built bundle.
    """
    key = _VITE_ENTRIES.get(entry, entry)

    if settings.debug and settings.vite_dev_server:
        base = settings.vite_dev_server.rstrip("/")
        return Markup(
            f'<script type="module" src="{base}/@vite/client"></script>\n'
            f'<script type="module" src="{base}/{key}"></script>'
        )

    manifest = _vite_manifest()
    chunk = manifest.get(key)
    if not chunk:
        return Markup("")
    tags: list[str] = []
    for css in chunk.get("css", []):
        tags.append(f'<link rel="stylesheet" href="/static/dist/{css}">')
    for imp in chunk.get("imports", []):
        dep = manifest.get(imp)
        if dep and dep.get("file"):
            tags.append(f'<link rel="modulepreload" href="/static/dist/{dep["file"]}">')
    tags.append(f'<script type="module" src="/static/dist/{chunk["file"]}"></script>')
    return Markup("\n".join(tags))


templates.env.globals["vite_asset"] = vite_asset


def vite_styles(entry: str = "styles") -> Markup:
    """Render a Vite CSS entry without adding an executable module script."""
    key = _VITE_ENTRIES.get(entry, entry)
    if settings.debug and settings.vite_dev_server:
        base = settings.vite_dev_server.rstrip("/")
        return Markup(f'<link rel="stylesheet" href="{base}/{key}">')

    chunk = _vite_manifest().get(key)
    if not chunk:
        return Markup("")
    files: list[str] = []
    output = chunk.get("file")
    if isinstance(output, str) and output.endswith(".css"):
        files.append(output)
    files.extend(css for css in chunk.get("css", []) if isinstance(css, str))
    return Markup(
        "\n".join(
            f'<link rel="stylesheet" href="/static/dist/{path}">' for path in dict.fromkeys(files)
        )
    )


templates.env.globals["vite_styles"] = vite_styles


# Block B: frontend-side 15s cache for the homepage runtime panel. The backend
# already caches /v1/stats/runtime at 20s; the previous value lingers as a
# stale-on-error fallback when the backend is briefly unavailable.
_RUNTIME_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_RUNTIME_TTL_SECONDS = 15
# Customer-facing aggregate health from hyrule-cloud's curated /v1/status
# contract. The header is server-rendered, so every informational page remains
# useful with JavaScript disabled.
_SERVICE_STATUS_CACHE: dict[str, Any] = {
    "value": None,
    "expires_at": 0.0,
    "successful_at": 0.0,
}
_SERVICE_STATUS_TTL_SECONDS = 15
_SERVICE_STATUS_STALE_SECONDS = 120
# Block H (Wave 5/6): fleet stats for /transparency. Longer TTL — these move
# slowly and the backend already caches /v1/stats/network for 30s.
_NETWORK_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_NETWORK_TTL_SECONDS = 30
# Block G (Wave 6): payment-networks catalog for /faq + /llms.txt. Crawlers hit
# llms.txt frequently — cache so we don't re-query the backend chain list per
# request.
_CATALOG_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_CATALOG_TTL_SECONDS = 60
# Overhaul: live VM product catalog (GET /v1/products/vms) for the tier grids.
# The hardcoded config.VM_TIERS once drifted from what the API provisions
# (512 MB vs 1 GB xs) — pages render the live catalog, config is fallback-only.
_PRODUCTS_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_PRODUCTS_TTL_SECONDS = 300
# Overhaul: the published x402 manifest (/.well-known/x402.json) — per-endpoint
# prices for /services and /agents. Slow-moving; fallback is the curated
# config.X402_RESOURCES_FALLBACK mirror.
_MANIFEST_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_MANIFEST_TTL_SECONDS = 300
# Overhaul: /v1/pricing (proxy route prices + currency/network) for /services.
_PRICING_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_PRICING_TTL_SECONDS = 300

_SERVICE_COMPONENTS = (
    ("api_checkout", "API & checkout", "Purchasing and management API"),
    ("compute", "Compute", "VM provisioning and reachability"),
    ("intelligence", "Network intelligence", "Network diagnostics endpoints"),
    ("domains_dns", "Domains & DNS", "Registration and authoritative DNS"),
    ("network_proxy", "Network proxy", "Direct, Tor, I2P, and Yggdrasil egress"),
)


def _unknown_service_status(
    message: str = "Current service health could not be confirmed.",
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "checked_at": None,
        "stale": True,
        "feed_unavailable": True,
        "components": [
            {"id": key, "name": name, "status": "unknown", "message": message}
            for key, name, _description in _SERVICE_COMPONENTS
        ],
        "incidents": [],
    }


def _service_status_view(status: dict[str, Any] | None) -> dict[str, Any]:
    status = status or _unknown_service_status()
    state = status.get("status", "unknown")
    raw_components = status.get("components")
    components: list[Any] = raw_components if isinstance(raw_components, list) else []
    affected = [
        component
        for component in components
        if isinstance(component, dict) and component.get("status") in {"degraded", "outage"}
    ]
    if status.get("stale"):
        return {"label": "Status feed delayed", "tone": "degraded", "affected": affected}
    if state == "outage":
        return {"label": "Major outage", "tone": "outage", "affected": affected}
    if state == "degraded":
        suffix = ""
        if len(affected) == 1:
            suffix = f" · {affected[0].get('name', 'service')}"
        elif affected:
            suffix = f" · {len(affected)} services"
        return {"label": f"Degraded{suffix}", "tone": "degraded", "affected": affected}
    if state == "operational":
        return {"label": "Operational", "tone": "operational", "affected": []}
    return {"label": "Status unavailable", "tone": "unknown", "affected": []}


async def _refresh_service_status(request: Request) -> dict[str, Any]:
    now = time.time()
    cached = _SERVICE_STATUS_CACHE.get("value")
    if isinstance(cached, dict) and now < float(_SERVICE_STATUS_CACHE["expires_at"]):
        successful_at = float(_SERVICE_STATUS_CACHE.get("successful_at", 0.0))
        stale_too_old = (
            cached.get("stale")
            and successful_at > 0
            and now - successful_at > _SERVICE_STATUS_STALE_SECONDS
        )
        if stale_too_old:
            unknown = _unknown_service_status("The live status feed is unavailable.")
            _SERVICE_STATUS_CACHE.update(
                value=unknown,
                expires_at=now + _SERVICE_STATUS_TTL_SECONDS,
                successful_at=0.0,
            )
            return unknown
        return cached

    client: httpx.AsyncClient | None = getattr(request.app.state, "http", None)
    data: dict[str, Any] | None = None
    if client is not None:
        try:
            response = await client.get("/v1/status", timeout=3.0)
            candidate = response.json() if response.status_code == 200 else None
            if isinstance(candidate, dict) and candidate.get("status") in {
                "operational",
                "degraded",
                "outage",
                "unknown",
            }:
                data = candidate
        except (httpx.HTTPError, ValueError):
            data = None

    if data is not None:
        _SERVICE_STATUS_CACHE.update(
            value=data,
            expires_at=now + _SERVICE_STATUS_TTL_SECONDS,
            successful_at=now,
        )
        return data

    successful_at = float(_SERVICE_STATUS_CACHE.get("successful_at", 0.0))
    if isinstance(cached, dict) and now - successful_at <= _SERVICE_STATUS_STALE_SECONDS:
        stale = {**cached, "stale": True, "feed_unavailable": True}
        _SERVICE_STATUS_CACHE.update(value=stale, expires_at=now + _SERVICE_STATUS_TTL_SECONDS)
        return stale
    unknown = _unknown_service_status("The live status feed is unavailable.")
    _SERVICE_STATUS_CACHE.update(
        value=unknown,
        expires_at=now + _SERVICE_STATUS_TTL_SECONDS,
        successful_at=0.0,
    )
    return unknown


@app.middleware("http")
async def refresh_service_status_for_pages(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    path = request.url.path
    excluded = (
        path.startswith("/api/")
        or path.startswith("/static/")
        or path in {
            "/favicon.ico",
            "/apple-touch-icon.png",
            "/apple-touch-icon-precomposed.png",
            "/robots.txt",
            "/sitemap.xml",
            "/llms.txt",
        }
    )
    if request.method == "GET" and not excluded:
        await _refresh_service_status(request)
    return await call_next(request)


def _copy(*parts: str) -> str:
    return " ".join(parts)


_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)


def _normalise_custom_domain(value: str) -> str | None:
    domain = value.strip().lower().rstrip(".")
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2:
        return None
    if any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        return None
    return domain


LEGAL_PAGES: dict[str, dict[str, Any]] = {
    "terms": {
        "title": "Terms",
        "description": "Terms for Hyrule Cloud VPS service.",
        "updated": "2026-06-02",
        "sections": [
            (
                "Service",
                [
                    _copy(
                        "Hyrule Cloud sells prepaid virtual machines on AS215932.",
                        "Orders include root SSH access, IPv6 connectivity, NAT64/DNS64",
                        "egress, and an automatic deploy.hyrule.host subdomain.",
                    ),
                    _copy(
                        "Runtime is prepaid for 1 to 365 days. Expired VMs may be",
                        "suspended or destroyed after the published grace period.",
                    ),
                ],
            ),
            (
                "Customer Responsibilities",
                [
                    _copy(
                        "You are responsible for activity from your VM, your SSH key,",
                        "and any management token or account credentials.",
                    ),
                    _copy(
                        "Do not use the service for malware command and control,",
                        "phishing, credential theft, DDoS, spam, CSAM, terrorism,",
                        "sanctions evasion, or activity that violates applicable law.",
                    ),
                ],
            ),
            (
                "Enforcement",
                [
                    _copy(
                        "We may suspend or destroy VMs after a precise abuse report,",
                        "credible security signal, court order, or law-enforcement request.",
                    ),
                    _copy(
                        "Where practical, we notify the customer and preserve an appeal",
                        "path. Some urgent safety or infrastructure cases require",
                        "immediate action.",
                    ),
                ],
            ),
            (
                "Payments",
                [
                    _copy(
                        "Crypto is accepted only as payment for hosting. Hyrule Cloud",
                        "does not custody, exchange, broker, transmit, or administer",
                        "crypto-assets for customers.",
                    ),
                    "Refunds and credits are handled manually and may require a support request.",
                ],
            ),
        ],
    },
    "privacy": {
        "title": "Privacy",
        "description": "Privacy details for Hyrule Cloud orders.",
        "updated": "2026-06-02",
        "sections": [
            (
                "Ordering Model",
                [
                    _copy(
                        "Hyrule Cloud uses a no-KYC ordering model and does not",
                        "require identity verification for hosting orders.",
                    ),
                    _copy(
                        "Anonymous checkout returns a one-time management token.",
                        "Account signup uses a random handle and a password you set.",
                    ),
                ],
            ),
            (
                "Data We Store",
                [
                    _copy(
                        "VM configuration, SSH public key, generated VM identifiers,",
                        "hostname, timestamps, payment status, and expiry state.",
                    ),
                    _copy(
                        "For x402 orders we store payer wallet metadata needed to",
                        "reconcile payment. For abuse rate-limiting we store a sha256",
                        "hash of your IPv6 /64 prefix with a private pepper.",
                    ),
                ],
            ),
            (
                "Data We Do Not Inspect",
                [
                    _copy(
                        "We do not run a monitoring agent inside customer VMs and do",
                        "not proactively inspect VM contents.",
                    ),
                    _copy(
                        "Network and host telemetry is used for reliability, abuse",
                        "response, and capacity planning.",
                    ),
                ],
            ),
            (
                "Retention",
                [
                    _copy(
                        "Operational records are kept only as long as needed for service",
                        "operation, accounting, abuse handling, and legal obligations.",
                    ),
                    _copy(
                        "Abuse reports may be retained with evidence, action taken,",
                        "customer notice, and appeal result.",
                    ),
                ],
            ),
        ],
    },
    "abuse": {
        "title": "Abuse",
        "description": "Report abuse involving Hyrule Cloud infrastructure.",
        "updated": "2026-06-02",
        "sections": [
            (
                "Report Channels",
                [
                    _copy(
                        "Send abuse reports, operational issues, and customer support",
                        "requests to support@hyrule.host. Use 'Abuse report' in the",
                        "subject for abuse cases.",
                    ),
                    _copy(
                        "Include a reporter contact, URL or hostname or IP, allegation,",
                        "evidence, timestamp with timezone, and any urgency indicators.",
                    ),
                ],
            ),
            (
                "Immediate Suspension Categories",
                [
                    _copy(
                        "Malware command and control, phishing, credential theft, DDoS,",
                        "spam, CSAM, terrorism, and valid court or law-enforcement orders",
                        "may result in immediate suspension.",
                    ),
                    _copy(
                        "We do not require broad personal data to act on precise,",
                        "technically actionable reports.",
                    ),
                ],
            ),
            (
                "Notice And Appeal",
                [
                    _copy(
                        "When it is safe and practical, we notify the customer through",
                        "their management surface or account and record the action taken.",
                    ),
                    _copy(
                        "Appeals can be sent to support@hyrule.host with the VM ID,",
                        "report reference, and remediation details.",
                    ),
                ],
            ),
            (
                "Queue Fields",
                [
                    _copy(
                        "The abuse queue tracks reporter contact, URL/hostname/IP,",
                        "allegation, evidence, timestamp, action taken, customer notice,",
                        "and appeal/result.",
                    ),
                ],
            ),
        ],
    },
    "legal": {
        "title": "Legal",
        "description": "Legal contact and service posture for Hyrule Cloud.",
        "updated": "2026-06-02",
        "sections": [
            (
                "Operator And Jurisdiction",
                [
                    _copy(
                        "Hyrule Cloud is operated from the Netherlands. Compute currently",
                        "runs at OVH France, with AS215932 network operations in the EU.",
                    ),
                    _copy(
                        "Hyrule Cloud is a hosting/intermediary service. It publishes",
                        "contact points, terms, and a notice/action flow for abuse handling.",
                    ),
                ],
            ),
            (
                "Crypto Payment Posture",
                [
                    _copy(
                        "Crypto payment support is limited to paying for hosting.",
                        "Hyrule Cloud does not provide customer wallets, exchange services,",
                        "brokerage, transmission, or custody.",
                    ),
                    _copy(
                        "New crypto-asset services such as stored balances, custody,",
                        "exchange, or wallet administration require legal review before launch.",
                    ),
                ],
            ),
            (
                "Domains",
                [
                    _copy(
                        "Every VM may receive a deploy.hyrule.host subdomain. Custom",
                        "domains can be registered during checkout and managed through",
                        "the domain management surface or account session.",
                    ),
                ],
            ),
            (
                "Authorities",
                [
                    _copy(
                        "Serious life, safety, or criminal reports may be escalated to",
                        "competent authorities as required by applicable law.",
                    ),
                ],
            ),
        ],
    },
}


def _render(request: Request, name: str, *, status_code: int = 200, **kwargs: Any) -> Response:
    """Render a template with common context variables.

    Injects the most recent runtime and customer-safe service-status snapshots.
    Templates stay useful when either backend feed is temporarily unavailable.
    """
    ctx: dict[str, Any] = {
        "vm_tiers": VM_TIERS,
        # Issue #14: public WalletConnect projectId for the base.html meta tag.
        "wc_project_id": settings.walletconnect_project_id,
        **kwargs,
    }
    if "runtime" not in ctx:
        ctx["runtime"] = _RUNTIME_CACHE.get("value")
    service_status = _SERVICE_STATUS_CACHE.get("value")
    if not isinstance(service_status, dict):
        service_status = _unknown_service_status()
    ctx["service_status"] = service_status
    ctx["status_view"] = _service_status_view(service_status)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _catalog_networks(catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
    networks = catalog.get("networks") if catalog else []
    return networks if isinstance(networks, list) else []


def _catalog_native(catalog: dict[str, Any] | None) -> list[str]:
    native = catalog.get("native") if catalog else []
    return [str(x).upper() for x in native] if isinstance(native, list) else []


def _sane_provision_seconds(value: Any) -> int | None:
    """Sanity-gate the advertised provision time. The backend's rolling
    average can be polluted by stuck/simulated builds (observed: 4720.3s
    while real provisions finish in seconds) — outside a plausible window
    we render the templates' honest "~60s" fallback instead of telemetry
    we don't believe."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if 0 < v <= 300:
        return round(v)
    return None


async def _refresh_runtime(request: Request) -> dict[str, Any] | None:
    """Pull /v1/stats/runtime, cache for 15s. Stale-on-error: if the fetch
    fails we serve the last good value rather than punching a hole through
    to None — better UX than a flicker between a real number and a dash."""
    now = time.time()
    cached: dict[str, Any] | None = _RUNTIME_CACHE.get("value")
    if cached is not None and now < float(_RUNTIME_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/stats/runtime")
    if data is not None:
        data = {
            **data,
            "avg_provision_seconds": _sane_provision_seconds(data.get("avg_provision_seconds")),
        }
        _RUNTIME_CACHE["value"] = data
        _RUNTIME_CACHE["expires_at"] = now + _RUNTIME_TTL_SECONDS
        return data
    # Hold the last good value past its TTL when the backend is down.
    return cached


async def _refresh_network(request: Request) -> dict[str, Any] | None:
    """Pull /v1/stats/network, cache for 30s. Stale-on-error, same as runtime.
    The backend itself returns _source="fallback" on Prometheus failure, so
    None here only means the backend itself is unreachable."""
    now = time.time()
    cached: dict[str, Any] | None = _NETWORK_CACHE.get("value")
    if cached is not None and now < float(_NETWORK_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/stats/network")
    if data is not None:
        _NETWORK_CACHE["value"] = data
        _NETWORK_CACHE["expires_at"] = now + _NETWORK_TTL_SECONDS
        return data
    return cached


async def _refresh_networks(request: Request) -> dict[str, Any] | None:
    """Pull /v1/payments/networks, cache 60s, stale-on-error. Shared by /faq and
    /llms.txt so crawlers hitting llms.txt don't re-query the chain list each time."""
    now = time.time()
    cached: dict[str, Any] | None = _CATALOG_CACHE.get("value")
    if cached is not None and now < float(_CATALOG_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/payments/networks")
    if data is not None:
        _CATALOG_CACHE["value"] = data
        _CATALOG_CACHE["expires_at"] = now + _CATALOG_TTL_SECONDS
        return data
    return cached


async def _refresh_cached(
    request: Request, cache: dict[str, Any], ttl_seconds: int, path: str
) -> dict[str, Any] | None:
    """Generic TTL + stale-on-error fetch used by the overhaul caches
    (products / manifest / pricing) — same semantics as the Block B/G ones."""
    now = time.time()
    cached: dict[str, Any] | None = cache.get("value")
    if cached is not None and now < float(cache["expires_at"]):
        return cached
    data = await _fetch_api(request, path)
    if data is not None:
        cache["value"] = data
        cache["expires_at"] = now + ttl_seconds
        return data
    return cached


async def _refresh_products(request: Request) -> dict[str, Any] | None:
    return await _refresh_cached(
        request, _PRODUCTS_CACHE, _PRODUCTS_TTL_SECONDS, "/v1/products/vms"
    )


async def _refresh_manifest(request: Request) -> dict[str, Any] | None:
    return await _refresh_cached(
        request, _MANIFEST_CACHE, _MANIFEST_TTL_SECONDS, "/.well-known/x402.json"
    )


async def _refresh_pricing(request: Request) -> dict[str, Any] | None:
    return await _refresh_cached(request, _PRICING_CACHE, _PRICING_TTL_SECONDS, "/v1/pricing")


def _live_vm_tiers(products: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map GET /v1/products/vms onto the template tier shape. Malformed rows
    are skipped (pr-agent #32: one bad row must not discard the whole live
    catalog); the static config mirror is the fallback only when nothing
    valid parses — the API is the source of truth for what actually gets
    provisioned."""
    rows = (products or {}).get("products")
    if not isinstance(rows, list):
        return VM_TIERS
    tiers: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            tiers[str(row["size"])] = {
                "name": str(row["name"]),
                "vcpu": int(row["vcpu"]),
                "ram_mb": int(row["ram_mb"]),
                "disk_gb": int(row["disk_gb"]),
                "price": float(row["price_usd_day"]),
            }
        except (KeyError, TypeError, ValueError):
            log.warn("products_row_malformed", row=str(row)[:200])
            continue
    return tiers or VM_TIERS


def _x402_group(path: str) -> str:
    """Bucket a manifest path into one of the four service pillars."""
    if path.startswith("/v1/vm"):
        return "compute"
    if path.startswith(("/v1/domain", "/v1/zone")):
        return "domains"
    if path.startswith("/v1/network"):
        return "proxy"
    return "intel"


def _x402_resources(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize the published manifest's resources for the price tables on
    /services and /agents; falls back to the curated config mirror."""
    rows = (manifest or {}).get("resources")
    if not isinstance(rows, list) or not rows:
        return X402_RESOURCES_FALLBACK
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = row.get("path")
        price = row.get("minPrice")
        if not isinstance(path, str) or price is None:
            continue
        out.append(
            {
                "path": path,
                "method": str(row.get("method", "POST")),
                "description": str(row.get("description", "")),
                "min_price": str(price),
                "group": _x402_group(path),
            }
        )
    return out or X402_RESOURCES_FALLBACK


def _proxy_prices(pricing: dict[str, Any] | None) -> dict[str, str]:
    """Per-route proxy prices from GET /v1/pricing, with a static fallback."""
    prices = (pricing or {}).get("proxy_prices")
    if isinstance(prices, dict) and prices:
        return {str(k): str(v) for k, v in prices.items()}
    return PROXY_PRICES_FALLBACK


async def _fetch_api(request: Request, path: str) -> dict[str, Any] | None:
    """GET a JSON endpoint from the backend API, return parsed dict or None."""
    try:
        resp = await request.app.state.http.get(path)
        if resp.status_code == 200:
            data: dict[str, Any] = resp.json()
            return data
        log.warn("api_non_200", path=path, status=resp.status_code)
    except httpx.HTTPError as exc:
        log.error(
            "api_fetch_failed",
            path=path,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
    return None


async def _fetch_vm_status(request: Request, vm_id: str) -> dict[str, Any] | None:
    """Fetch the launch-proof status for a single VM."""
    return await _fetch_api(request, f"/v1/vm/{vm_id}/status")


async def _api_request(
    request: Request,
    path: str,
    *,
    method: str = "GET",
    json: dict[str, Any] | None = None,
    forward_cookie: bool = True,
) -> httpx.Response | None:
    """Issue a backend call from a server-side handler, optionally forwarding
    the browser's session cookie so account-scoped endpoints work.

    Returns the raw httpx.Response (not just parsed JSON) so the caller can
    inspect status codes and pass Set-Cookie back via _copy_set_cookie."""
    client: httpx.AsyncClient = request.app.state.http
    headers: dict[str, str] = {}
    if forward_cookie:
        cookie = request.headers.get("cookie")
        if cookie:
            headers["cookie"] = cookie
    try:
        return await client.request(method=method, url=path, headers=headers, json=json)
    except httpx.HTTPError as exc:
        log.error("api_request_failed", path=path, method=method, error=str(exc))
        return None


def _copy_set_cookie(backend_resp: httpx.Response, response: Response) -> None:
    """Copy backend Set-Cookie headers onto our outgoing response so login/
    register sessions reach the browser. Preserves multiple Set-Cookie values
    via raw_headers (a single Response.headers dict would collapse duplicates)."""
    for k, v in backend_resp.headers.multi_items():
        if k.lower() == "set-cookie":
            response.raw_headers.append((b"set-cookie", v.encode("latin-1")))


def _require_auth_ui() -> None:
    """Wave 2 kill-switch — flip HYRULE_WEB_ENABLE_AUTH_UI=false to dark the
    /signup /login /recover /dashboard surface without redeploying."""
    if not settings.enable_auth_ui:
        raise HTTPException(status_code=404)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request) -> Response:
    """Block B: the homepage renders backend runtime stats in its infrastructure
    panel, cached for 15s and stale-on-error.

    Issue #14: the settlement-chain copy is also driven from the live
    /v1/payments/networks list (single source of truth, same as /faq and
    llms.txt) — never hardcoded — per [[feedback_verified_payment_chains]]."""
    runtime = await _refresh_runtime(request)
    catalog = await _refresh_networks(request)
    resources = _x402_resources(await _refresh_manifest(request))
    return _render(
        request,
        "index.html",
        runtime=runtime,
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        vm_tiers=_live_vm_tiers(await _refresh_products(request)),
        x402_resources=resources,
    )


@app.get("/services", response_class=HTMLResponse)
async def page_services(request: Request) -> Response:
    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    resources = _x402_resources(await _refresh_manifest(request))
    return _render(
        request,
        "services.html",
        os_templates=os_list,
        vm_tiers=_live_vm_tiers(await _refresh_products(request)),
        x402_resources=resources,
        proxy_prices=_proxy_prices(await _refresh_pricing(request)),
    )


@app.get("/agents", response_class=HTMLResponse)
async def page_agents(request: Request) -> Response:
    """Overhaul: the x402 story for agents — manifest, golden path, per-endpoint
    prices (live from the published manifest, curated fallback), MCP config,
    ClawHub skills, and the live payment-rail list."""
    catalog = await _refresh_networks(request)
    resources = _x402_resources(await _refresh_manifest(request))
    return _render(
        request,
        "agents.html",
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        x402_resources=resources,
    )


@app.get("/order", response_class=HTMLResponse)
async def page_order(request: Request) -> Response:
    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "order.html",
        os_templates=os_list,
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        vm_tiers=_live_vm_tiers(await _refresh_products(request)),
        order_error=None,
        form_values={},
    )


@app.get("/status", response_class=HTMLResponse)
async def page_service_status(request: Request) -> Response:
    await _refresh_service_status(request)
    return _render(request, "service_status.html")


@app.get("/order/status", include_in_schema=False)
async def legacy_service_status_redirect() -> RedirectResponse:
    return RedirectResponse("/status", status_code=308)


@app.post("/order/review")
async def page_review(
    request: Request,
    os: Annotated[str, Form()],
    size: Annotated[str, Form()],
    duration: Annotated[int, Form()],
    ssh_pubkey: Annotated[str, Form()],
    hostname: Annotated[str, Form()] = "",
    domain_mode: Annotated[str, Form()] = "auto",
    domain: Annotated[str, Form()] = "",
) -> Response:
    form_values = {
        "os": os,
        "size": size,
        "duration": duration,
        "ssh_pubkey": ssh_pubkey,
        "hostname": hostname,
        "domain_mode": domain_mode,
        "domain": domain,
    }
    vm_tiers = _live_vm_tiers(await _refresh_products(request))
    custom_domain = _normalise_custom_domain(domain) if domain_mode == "custom" else None
    error: str | None = None
    if size not in vm_tiers:
        error = "Choose a valid server size."
    elif not 1 <= duration <= 365:
        error = "Duration must be between 1 and 365 days."
    elif domain_mode not in {"auto", "custom"}:
        error = "Choose automatic or custom domain setup."
    elif domain_mode == "custom" and custom_domain is None:
        error = "Enter a valid fully-qualified domain name."

    if error is None:
        order_payload: dict[str, Any] = {
            "os": os,
            "size": size,
            "duration_days": duration,
            "ssh_pubkey": ssh_pubkey,
            "domain_mode": domain_mode,
        }
        if custom_domain is not None:
            order_payload["domain"] = custom_domain
        backend = await _api_request(
            request,
            "/v1/vm/quote",
            method="POST",
            json={"order_payload": order_payload},
        )
        if backend is not None and backend.status_code in {200, 201}:
            try:
                quote_id = backend.json().get("quote_id")
            except ValueError:
                quote_id = None
            if isinstance(quote_id, str) and quote_id:
                review_path = f"/order/review/{urllib.parse.quote(quote_id, safe='')}"
                return RedirectResponse(review_path, status_code=303)
        if backend is not None:
            try:
                detail = backend.json().get("detail")
            except ValueError:
                detail = None
            error = (
                str(detail)
                if detail
                else "The quote could not be created. Check the form and try again."
            )
        else:
            error = "The ordering API is temporarily unavailable. Your form has not been submitted."

    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "order.html",
        os_templates=os_list,
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        vm_tiers=vm_tiers,
        order_error=error,
        form_values=form_values,
        status_code=422,
    )


@app.get("/order/review/{quote_id}", response_class=HTMLResponse)
async def page_review_quote(request: Request, quote_id: str) -> Response:
    """Issue #14: reload-safe review page backed by a durable quote.

    The order form (order.ts) creates a quote and sends the browser here, so a
    mobile wallet handoff that reloads the page just re-GETs this URL and the
    order is re-rendered from the backend — no lost POST body. Unknown quote →
    back to the order form; expired quote → render with a restart banner."""
    quote = await _fetch_api(request, f"/v1/vm/quote/{quote_id}")
    if not quote:
        return RedirectResponse("/order", status_code=303)

    payload: dict[str, Any] = quote.get("order_payload") or {}
    size = payload.get("size", "sm")
    duration = payload.get("duration_days", 30)
    vm_tiers = _live_vm_tiers(await _refresh_products(request))
    tier = vm_tiers.get(size, VM_TIERS["sm"])
    try:
        total = Decimal(str(quote["amount_usd"]))
    except (KeyError, InvalidOperation):
        total = Decimal(str(tier["price"])) * duration
    order = {
        "os": payload.get("os"),
        "size": size,
        "duration": duration,
        "ssh_pubkey": payload.get("ssh_pubkey", ""),
        # hostname is not part of the backend VM spec; the quote doesn't carry it.
        "hostname": "",
        "domain_mode": payload.get("domain_mode", "auto"),
        "domain": payload.get("domain") or "",
        "id": quote_id,
        "quote_id": quote_id,
        "amount_usd": total,
        "expired": quote.get("status") == "expired",
        "payment_methods": quote.get("accepted_payment_methods") or {},
    }
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "review.html",
        order=order,
        tier=tier,
        total=total,
        vm_tiers=vm_tiers,
        networks=_catalog_networks(catalog),
    )


@app.get("/order/status/{vm_id}", response_class=HTMLResponse)
async def page_status(request: Request, vm_id: str) -> Response:
    # Block A0: status page calls the sanitized public endpoint. The
    # legacy /v1/vm/{id} is now management-gated and would 404 here.
    data = await _fetch_vm_status(request, vm_id)
    # If the URL carries ?token=hyr_vm_..., the user just landed from a
    # fresh anon order. Surface the management URL banner exactly once.
    token = request.query_params.get("token")
    management_url = None
    if token and token.startswith("hyr_vm_"):
        scheme = request.url.scheme
        host = request.headers.get("host", "")
        # Routed via Caddy on proxy → api:8402. The cloud subdomain serves
        # the api directly so the management URL is the canonical form an
        # agent or curl would use. Token is URL-encoded — current tokens are
        # `hyr_vm_<32 base62>` (no reserved chars), but encoding now keeps the
        # URL well-formed if the token shape ever picks up `&`, `?`, or `=`.
        management_url = (
            f"{scheme}://cloud.{host.removeprefix('www.')}/v1/vm/{vm_id}"
            f"?token={urllib.parse.quote(token, safe='')}"
        )
    return _render(
        request, "status.html",
        vm_id=vm_id, vm=data, management_url=management_url,
    )


# ---------------------------------------------------------------------------
# Block A1 — auth pages (signup / login / logout / recover / dashboard)
# ---------------------------------------------------------------------------


@app.get("/signup", response_class=HTMLResponse)
async def page_signup(request: Request) -> Response:
    _require_auth_ui()
    return _render(request, "signup.html", error=None)


@app.post("/signup", response_class=HTMLResponse)
async def do_signup(
    request: Request,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
) -> Response:
    """Mirror the backend's password rules (min 12 chars) before round-tripping
    so we can return an inline error without burning the per-IP signup quota
    on /v1/auth/register."""
    _require_auth_ui()
    if password != password_confirm:
        return _render(request, "signup.html", error="Passwords do not match.")
    if len(password) < 12:
        return _render(request, "signup.html", error="Password must be at least 12 characters.")

    backend = await _api_request(
        request, "/v1/auth/register", method="POST", json={"password": password}
    )
    if backend is None:
        return _render(request, "signup.html", error="Backend unreachable. Try again.")
    if backend.status_code == 429:
        return _render(
            request, "signup.html",
            error="Too many signups from your network; try later.",
        )
    if backend.status_code != 200:
        return _render(request, "signup.html", error="Signup failed. Try again.")

    body = backend.json()
    # signup_success is the *only* place the recovery code is ever shown.
    # Render via _render so the Set-Cookie from /v1/auth/register can be
    # attached to the same response object (browser is now logged in).
    rendered = _render(
        request, "signup_success.html",
        account_id=body["account_id"],
        recovery_code=body["recovery_code"],
    )
    _copy_set_cookie(backend, rendered)
    return rendered


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request) -> Response:
    _require_auth_ui()
    return _render(request, "login.html", error=None)


@app.post("/login", response_class=HTMLResponse)
async def do_login(
    request: Request,
    account_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    backend = await _api_request(
        request, "/v1/auth/login", method="POST",
        json={"account_id": account_id.strip().upper(), "password": password},
    )
    if backend is None:
        return _render(request, "login.html", error="Backend unreachable.")
    if backend.status_code == 429:
        return _render(request, "login.html", error="Too many login attempts; try later.")
    if backend.status_code != 200:
        return _render(request, "login.html", error="Invalid credentials.")

    redirect = RedirectResponse("/dashboard", status_code=303)
    _copy_set_cookie(backend, redirect)
    return redirect


@app.post("/logout", response_class=HTMLResponse)
async def do_logout(request: Request) -> Response:
    _require_auth_ui()
    backend = await _api_request(request, "/v1/auth/logout", method="POST")
    redirect = RedirectResponse("/", status_code=303)
    # Even if the backend call fails (e.g. session already expired) the
    # /v1/auth/logout endpoint sets an expiring cookie; forward it so the
    # browser drops the stale hyr_sess cookie.
    if backend is not None:
        _copy_set_cookie(backend, redirect)
    return redirect


@app.get("/recover", response_class=HTMLResponse)
async def page_recover(request: Request) -> Response:
    _require_auth_ui()
    return _render(request, "recover.html", error=None, success=None)


@app.post("/recover", response_class=HTMLResponse)
async def do_recover(
    request: Request,
    account_id: Annotated[str, Form()],
    recovery_code: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    if new_password != new_password_confirm:
        return _render(request, "recover.html", error="Passwords do not match.", success=None)
    if len(new_password) < 12:
        return _render(
            request, "recover.html",
            error="Password must be at least 12 characters.", success=None,
        )

    backend = await _api_request(
        request, "/v1/auth/recover/code", method="POST",
        json={
            "account_id": account_id.strip().upper(),
            "recovery_code": recovery_code.strip(),
            "new_password": new_password,
        },
    )
    if backend is None:
        return _render(request, "recover.html", error="Backend unreachable.", success=None)
    if backend.status_code == 429:
        return _render(
            request, "recover.html",
            error="Too many recovery attempts; try later.", success=None,
        )
    if backend.status_code != 200:
        return _render(
            request, "recover.html",
            error="Invalid recovery code or account ID.", success=None,
        )

    body = backend.json()
    return _render(
        request, "recover.html",
        error=None,
        success={
            "account_id": body["account_id"],
            "new_recovery_code": body["new_recovery_code"],
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request) -> Response:
    """Renders the signed-in dashboard. /v1/me 401 → redirect to /login. Any
    other backend failure renders the shell with an error banner so the user
    can still log out / claim a VM without a forced loop."""
    _require_auth_ui()
    me_resp = await _api_request(request, "/v1/me")
    if me_resp is None or me_resp.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if me_resp.status_code != 200:
        return _render(
            request, "dashboard.html",
            me=None, vms=[], error="Could not load account info.",
        )
    me = me_resp.json()
    vms_resp = await _api_request(request, "/v1/me/vms")
    vms = vms_resp.json().get("vms", []) if (vms_resp and vms_resp.status_code == 200) else []
    return _render(request, "dashboard.html", me=me, vms=vms, error=None)


# Block A1: dashboard mutation handlers — all server-side, all redirect back
# to /dashboard on completion so the browser's history stays clean and the
# user always lands on a fresh table read.


@app.post("/dashboard/vms/{vm_id}/reboot")
async def dash_reboot(request: Request, vm_id: str) -> Response:
    _require_auth_ui()
    await _api_request(request, f"/v1/vm/{vm_id}/reboot", method="POST")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/vms/{vm_id}/destroy")
async def dash_destroy(request: Request, vm_id: str) -> Response:
    _require_auth_ui()
    await _api_request(request, f"/v1/vm/{vm_id}", method="DELETE")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/claim")
async def dash_claim(
    request: Request,
    vm_id: Annotated[str, Form()],
    token: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    await _api_request(
        request, f"/v1/me/vms/{vm_id.strip()}/claim", method="POST",
        json={"token": token.strip()},
    )
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/password")
async def dash_change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    await _api_request(
        request, "/v1/me/password", method="POST",
        json={"current_password": current_password, "new_password": new_password},
    )
    return RedirectResponse("/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# SEO surface — robots.txt, sitemap.xml, llms.txt
# ---------------------------------------------------------------------------


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    return ROBOTS_TXT


# Serve the brand icons at the well-known root paths too (browsers and crawlers
# request /favicon.ico directly, not just the <link>-referenced /static path).
# Brand marks change rarely, so cache for a week; no `immutable` because the URL
# is stable (not content-hashed) and we want a rebrand to still revalidate.
_ICON_CACHE_CONTROL = "public, max-age=604800"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "favicon.ico",
        media_type="image/x-icon",
        headers={"Cache-Control": _ICON_CACHE_CONTROL},
    )


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "apple-touch-icon.png",
        media_type="image/png",
        headers={"Cache-Control": _ICON_CACHE_CONTROL},
    )


@app.get("/transparency", response_class=HTMLResponse)
async def page_transparency(request: Request) -> Response:
    """Infra-truth page: ASN, hosts, peering, jurisdiction (Block G). Live fleet
    numbers (BGP peers, NAT64 sessions, IPv6 prefixes) come from
    /v1/stats/network; falls back to the static shape when it's unreachable."""
    await _refresh_runtime(request)
    network = await _refresh_network(request)
    return _render(request, "transparency.html", network=network)


@app.get("/faq", response_class=HTMLResponse)
async def page_faq(request: Request) -> Response:
    """FAQ + FAQPage JSON-LD (Block G). Only mentions live payment methods —
    the chain list comes from /v1/payments/networks, never hardcoded."""
    await _refresh_runtime(request)
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "faq.html",
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
    )


@app.get("/terms", response_class=HTMLResponse)
async def page_terms(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["terms"])


@app.get("/privacy", response_class=HTMLResponse)
async def page_privacy(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["privacy"])


@app.get("/abuse", response_class=HTMLResponse)
async def page_abuse(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["abuse"])


@app.get("/legal", response_class=HTMLResponse)
async def page_legal(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["legal"])


@app.get("/sitemap.xml")
async def sitemap() -> Response:
    return Response(content=render_sitemap_xml(app), media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms(request: Request) -> str:
    # Build from live backend state so the doc never advertises a disabled
    # chain (feedback_verified_payment_chains). None → "ask the API" note.
    networks_resp = await _refresh_networks(request)
    networks = networks_resp.get("networks") if networks_resp else None
    native = networks_resp.get("native") if networks_resp else None
    # The diagnostics section requires a payable x402 chain confirmed by a
    # FRESH catalog — _refresh_networks serves stale-on-error, and a stale
    # catalog is not evidence the paid endpoints are reachable right now.
    fresh = time.time() < float(_CATALOG_CACHE.get("expires_at", 0.0))
    return build_llms_txt(networks, native=native, diagnostics_live=fresh)


# ---------------------------------------------------------------------------
# API proxy — browser talks to same origin, we forward to the backend API
# ---------------------------------------------------------------------------


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_api(request: Request, path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.http
    api_path = path[3:] if path.startswith("v1/") else path

    forward_headers: dict[str, str] = {}
    for key in request.headers:
        lower = key.lower()
        if lower in (
            "content-type", "accept",
            "x-payment", "x-dev-bypass", "payment-signature",
            # Block A0: Bearer auth for hyr_vm_ management tokens (and
            # future hyr_sk_ account API keys in Block D).
            "authorization",
            # Block A1: forward session cookies so the backend can resolve
            # the current account on /me/* calls coming from the browser.
            "cookie",
        ):
            forward_headers[key] = request.headers[key]

    body = await request.body()

    try:
        resp = await client.request(
            method=request.method,
            url=f"/v1/{api_path}",
            headers=forward_headers,
            content=body if body else None,
        )
    except httpx.HTTPError as exc:
        return Response(
            content=f'{{"error": "API unreachable: {exc}"}}',
            status_code=502,
            media_type="application/json",
        )

    # Build the proxied response. Starlette's Response constructor takes a
    # dict for headers, which collapses duplicates — so we put the standard
    # headers there and then append any Set-Cookie values via raw_headers,
    # which preserves multiplicity (login can set hyr_sess + hyr_csrf in one).
    skip = ("transfer-encoding", "content-encoding", "content-length", "set-cookie")
    base_headers: dict[str, str] = {
        k: v for k, v in resp.headers.items() if k.lower() not in skip
    }
    proxied = Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=base_headers,
    )
    for k, v in resp.headers.multi_items():
        if k.lower() == "set-cookie":
            proxied.raw_headers.append((b"set-cookie", v.encode("latin-1")))
    return proxied


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    import uvicorn

    uvicorn.run(
        "hyrule_web.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
